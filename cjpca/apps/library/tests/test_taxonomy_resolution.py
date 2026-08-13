"""Phase 0 — concept resolution against the official taxonomy.

Covers the four resolution paths (exact / alias / normalized / semantic), the
three outcomes they can produce, and the invariants the paths depend on.

The distinction under test throughout is MATCHED vs UNRESOLVED vs UNCLASSIFIED.
Those are three different statements — "this is an official topic", "this is a
real concept the taxonomy lacks", "there is nothing to classify here" — and
collapsing any two of them either buries a genuine taxonomy gap or floods the
review queue with noise.

Pure unit tests: no database, no model. The semantic path is exercised with a
stub embedder so the suite never loads a SentenceTransformer.
"""

from django.test import SimpleTestCase

from reasoning import taxonomy as tx
from reasoning.taxonomy import (
    ALIASES, MATCHED, TAXONOMY, TAXONOMY_LINEAGE, TAXONOMY_VERSION,
    UNCLASSIFIED, UNRESOLVED, ConceptResolution, METHOD_ALIAS, METHOD_EXACT,
    METHOD_NORMALIZED, METHOD_SEMANTIC, METHOD_NONE,
    lineage_is_current, normalise_concept, resolve_concept, resolve_concepts,
    tags_still_valid_since, validate_aliases,
)


# ── stub embedder ────────────────────────────────────────────────────────────
#
# cosine([1,0], [x, sqrt(1-x^2)]) == x, so a score is dialled in exactly by
# choosing the first component. That makes threshold/margin behaviour testable
# without a real embedding model and without flaky float tolerances.

def _vec(score: float) -> list[float]:
    return [score, max(0.0, 1.0 - score ** 2) ** 0.5]


def make_embed_fn(target: tuple, best: float = 0.90, runner: float = 0.50):
    """embed_fn scoring `target` (topic, subcategory) at `best`, others `runner`."""
    targets = tx._semantic_targets()

    def _embed(texts: list[str]) -> list[list[float]]:
        # texts[0] is the probe; the rest align 1:1 with _semantic_targets().
        out = [[1.0, 0.0]]
        for topic, sub, _label in targets:
            out.append(_vec(best if (topic, sub) == target else runner))
        assert len(out) == len(texts), 'stub embedder desynced from targets'
        return out
    return _embed


class TaxonomyStructureUnchangedTests(SimpleTestCase):
    """The vocabulary is pinned. If a phase moved a leaf, every cached tag in
    the corpus silently became stale — so both the shape and the exact
    fingerprint are asserted."""

    def test_twelve_topics(self):
        self.assertEqual(len(TAXONOMY), 12)

    def test_fingerprint_is_self_consistent(self):
        self.assertEqual(TAXONOMY_VERSION, tx.fingerprint_of(TAXONOMY))

    def test_fingerprint_is_pinned(self):
        """The single site pinning the literal. It fails whenever the taxonomy
        content OR the hashing algorithm changes — which is exactly when a
        human should be reading the lineage entry that explains why."""
        self.assertEqual(TAXONOMY_VERSION, 'v2-a894a88f')

    def test_schema_prefix_marks_the_algorithm_generation(self):
        """The prefix is what keeps a v1 fingerprint distinguishable from a v2
        one, so a stored version can never be mistaken for having been produced
        under the current algorithm."""
        self.assertTrue(TAXONOMY_VERSION.startswith('v2-'))
        self.assertNotEqual(TAXONOMY_VERSION, tx.LEGACY_V1_VERSION)

    def test_subcategory_tags_are_globally_unique(self):
        """resolve_concept()'s bare-subcategory exact path depends on this.
        If a future edit reuses a subcategory tag under two topics, that path
        becomes ambiguous — this test is what makes that fail loudly."""
        seen: dict = {}
        for topic, body in TAXONOMY.items():
            for sub in body['subcategories']:
                self.assertNotIn(sub, seen,
                                 f'{sub!r} appears under both {seen.get(sub)} and {topic}')
                seen[sub] = topic
        self.assertEqual(len(seen), 44)


class LineageTests(SimpleTestCase):

    def test_lineage_head_matches_current_version(self):
        """An edit to TAXONOMY without a lineage entry is the failure mode this
        guards: the tags are not corrupt, but nothing can say whether they
        survived the edit."""
        self.assertTrue(
            lineage_is_current(),
            f'TAXONOMY_LINEAGE head is {TAXONOMY_LINEAGE[-1]["version"]!r} but the '
            f'taxonomy now fingerprints as {TAXONOMY_VERSION!r}. Append a lineage '
            f'entry describing what changed.')

    def test_current_version_tags_are_valid(self):
        self.assertTrue(tags_still_valid_since(TAXONOMY_VERSION))

    def test_unknown_version_is_not_assumed_valid(self):
        self.assertFalse(tags_still_valid_since('v0-deadbeef'))
        self.assertFalse(tags_still_valid_since(''))

    def test_additive_change_keeps_older_tags_valid(self):
        """The whole point of the lineage: adding a topic must not force a
        corpus-wide re-classification."""
        patched = TAXONOMY_LINEAGE + [
            {'version': 'v1-newhash', 'change': tx.LINEAGE_ADDITIVE,
             'added': ['automated_decisions'], 'removed': [], 'note': ''},
        ]
        with self.settings():
            original = tx.TAXONOMY_LINEAGE
            tx.TAXONOMY_LINEAGE = patched
            try:
                self.assertTrue(tags_still_valid_since('v1-fea40d25'))
            finally:
                tx.TAXONOMY_LINEAGE = original

    def test_restructure_invalidates_older_tags(self):
        patched = TAXONOMY_LINEAGE + [
            {'version': 'v2-newhash', 'change': tx.LINEAGE_RESTRUCTURE,
             'added': [], 'removed': ['retention/archive_and_backup'], 'note': ''},
        ]
        original = tx.TAXONOMY_LINEAGE
        tx.TAXONOMY_LINEAGE = patched
        try:
            self.assertFalse(tags_still_valid_since('v1-fea40d25'))
        finally:
            tx.TAXONOMY_LINEAGE = original


class FingerprintStructureTests(SimpleTestCase):
    """The v2 fingerprint must react to EVERY structural change.

    v1 hashed leaves only, which left two holes: a top-level topic carrying no
    subcategories contributed nothing at all, and label edits went undetected
    even though the classifier is shown labels and the resolver matches against
    them. Both are covered here against hypothetical structures — the live
    TAXONOMY is never modified.
    """

    def _base(self):
        return {t: {'label': b['label'], 'subcategories': dict(b['subcategories'])}
                for t, b in TAXONOMY.items()}

    def test_adding_a_subcategory_changes_the_fingerprint(self):
        s = self._base()
        s['retention']['subcategories']['new_leaf'] = 'New leaf'
        self.assertNotEqual(tx.fingerprint_of(s), TAXONOMY_VERSION)

    def test_adding_a_top_level_topic_with_no_subcategories_changes_it(self):
        """THE v1 HOLE. Under the old algorithm this produced an identical
        fingerprint, so every consumer kept serving stale tags with no
        staleness signal at all."""
        s = self._base()
        s['electronic_transactions'] = {'label': 'Electronic transactions',
                                        'subcategories': {}}
        self.assertNotEqual(tx.fingerprint_of(s), TAXONOMY_VERSION)

    def test_removing_a_topic_changes_the_fingerprint(self):
        s = self._base()
        del s['retention']
        self.assertNotEqual(tx.fingerprint_of(s), TAXONOMY_VERSION)

    def test_removing_a_subcategory_changes_the_fingerprint(self):
        s = self._base()
        del s['retention']['subcategories']['secure_disposal']
        self.assertNotEqual(tx.fingerprint_of(s), TAXONOMY_VERSION)

    def test_renaming_a_subcategory_tag_changes_the_fingerprint(self):
        s = self._base()
        s['retention']['subcategories']['disposal'] = \
            s['retention']['subcategories'].pop('secure_disposal')
        self.assertNotEqual(tx.fingerprint_of(s), TAXONOMY_VERSION)

    def test_changing_a_subcategory_label_changes_the_fingerprint(self):
        """Labels are shown to the classifier by render_for_prompt() and are
        matched against by resolve_concept(), so editing one changes behaviour
        and must change the version."""
        s = self._base()
        s['retention']['subcategories']['secure_disposal'] = 'Destruction of data'
        self.assertNotEqual(tx.fingerprint_of(s), TAXONOMY_VERSION)

    def test_changing_a_topic_label_changes_the_fingerprint(self):
        s = self._base()
        s['retention']['label'] = 'Keeping and destroying data'
        self.assertNotEqual(tx.fingerprint_of(s), TAXONOMY_VERSION)

    def test_declaration_order_does_not_affect_the_fingerprint(self):
        s = dict(reversed(list(self._base().items())))
        for body in s.values():
            body['subcategories'] = dict(reversed(list(body['subcategories'].items())))
        self.assertEqual(tx.fingerprint_of(s), TAXONOMY_VERSION)

    def test_fingerprint_is_deterministic_across_calls(self):
        self.assertEqual(tx.fingerprint_of(self._base()),
                         tx.fingerprint_of(self._base()))

    def test_topic_and_leaf_namespaces_cannot_collide(self):
        """A topic named X and a leaf path X must not produce the same token."""
        a, b = self._base(), self._base()
        a['shared'] = {'label': '', 'subcategories': {}}
        b['retention']['subcategories']['shared'] = ''
        self.assertNotEqual(tx.fingerprint_of(a), tx.fingerprint_of(b))

    def test_fingerprint_of_does_not_mutate_its_argument(self):
        s = self._base()
        before = {t: sorted(x['subcategories']) for t, x in s.items()}
        tx.fingerprint_of(s)
        self.assertEqual({t: sorted(x['subcategories']) for t, x in s.items()},
                         before)

    def test_hypothetical_structures_never_touch_the_live_taxonomy(self):
        s = self._base()
        s['invented'] = {'label': 'Invented', 'subcategories': {'x': 'X'}}
        tx.fingerprint_of(s)
        self.assertEqual(len(TAXONOMY), 12)
        self.assertNotIn('invented', TAXONOMY)


class FingerprintPredictionTests(SimpleTestCase):
    """fingerprint_with() must predict what the FILE will hash to."""

    def test_no_additions_reproduces_the_current_version(self):
        self.assertEqual(tx.fingerprint_with(), TAXONOMY_VERSION)
        self.assertEqual(tx.fingerprint_with([]), TAXONOMY_VERSION)

    def test_bare_topic_addition_is_representable(self):
        """Only meaningful under v2 — under v1 a bare topic hashed to nothing."""
        self.assertNotEqual(tx.fingerprint_with(['electronic_transactions']),
                            TAXONOMY_VERSION)

    def test_prediction_matches_the_structure_actually_built(self):
        """The contract that matters: the predicted version must equal the
        fingerprint of the taxonomy once the change is really applied."""
        predicted = tx.fingerprint_with(
            ['adm/registers'], labels={'adm': 'Automated decisions',
                                       'adm/registers': 'ADM registers'})
        applied = {t: {'label': b['label'],
                       'subcategories': dict(b['subcategories'])}
                   for t, b in TAXONOMY.items()}
        applied['adm'] = {'label': 'Automated decisions',
                          'subcategories': {'registers': 'ADM registers'}}
        self.assertEqual(predicted, tx.fingerprint_of(applied))

    def test_labels_affect_the_prediction(self):
        self.assertNotEqual(
            tx.fingerprint_with(['adm'], labels={'adm': 'Automated decisions'}),
            tx.fingerprint_with(['adm'], labels={'adm': 'Something else'}))

    def test_prediction_does_not_mutate_the_taxonomy(self):
        before = len(TAXONOMY)
        tx.fingerprint_with(['brand_new/leaf'], labels={'brand_new': 'X'})
        self.assertEqual(len(TAXONOMY), before)
        self.assertEqual(TAXONOMY_VERSION, tx.fingerprint_of(TAXONOMY))


class AlgorithmTransitionTests(SimpleTestCase):
    """v1 -> v2 must not misrepresent history."""

    def test_the_legacy_version_is_still_recorded(self):
        self.assertEqual(tx.LEGACY_V1_VERSION, 'v1-fea40d25')
        self.assertIsNotNone(tx.lineage_entry('v1-fea40d25'))

    def test_the_transition_is_recorded_in_the_lineage(self):
        entry = tx.lineage_entry(TAXONOMY_VERSION)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['change'], tx.LINEAGE_ALGORITHM)

    def test_the_transition_added_and_removed_nothing(self):
        """The vocabulary did not change — only how it is hashed."""
        entry = tx.lineage_entry(TAXONOMY_VERSION)
        self.assertEqual(entry['added'], [])
        self.assertEqual(entry['removed'], [])
        self.assertEqual(len(TAXONOMY), 12)

    def test_tags_from_the_legacy_version_remain_semantically_valid(self):
        """They classified against exactly the same twelve topics, so an
        algorithm change must not declare them wrong."""
        self.assertTrue(tags_still_valid_since('v1-fea40d25'))

    def test_an_unrecognised_version_is_still_treated_conservatively(self):
        for unknown in ('v1-deadbeef', 'v2-deadbeef', 'v0-old', ''):
            with self.subTest(unknown=unknown):
                self.assertFalse(tags_still_valid_since(unknown))

    def test_a_restructure_after_the_transition_still_invalidates(self):
        patched = TAXONOMY_LINEAGE + [
            {'version': 'v2-later', 'change': tx.LINEAGE_RESTRUCTURE,
             'added': [], 'removed': ['retention'], 'note': ''},
        ]
        original = tx.TAXONOMY_LINEAGE
        tx.TAXONOMY_LINEAGE = patched
        try:
            self.assertFalse(tags_still_valid_since('v1-fea40d25'))
            self.assertFalse(tags_still_valid_since(TAXONOMY_VERSION))
        finally:
            tx.TAXONOMY_LINEAGE = original

    def test_v1_and_v2_fingerprints_cannot_collide(self):
        self.assertTrue(tx.LEGACY_V1_VERSION.startswith('v1-'))
        self.assertTrue(TAXONOMY_VERSION.startswith('v2-'))


class AliasTableTests(SimpleTestCase):

    def test_every_alias_resolves_to_a_real_leaf(self):
        problems = validate_aliases()
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_ambiguous_wording_is_deliberately_absent(self):
        """'sanctions' is aml_and_sanctions in a banking clause and penalties in
        an enforcement one. Aliasing it would make the resolver confidently
        wrong half the time."""
        self.assertNotIn('sanctions', ALIASES)


class EvidenceBackedAliasTests(SimpleTestCase):
    """The four wordings the Phase 2 dry run produced over the real corpus.

    Each was proposed by the classifier as a NEW official topic because nothing
    mapped it, and each came from a requirement that got ZERO official topics.
    All four are concepts the taxonomy already covers, so the correct fix is a
    vocabulary alias — not a thirteenth topic.
    """

    EXPECTED = {
        'cyber risk management':        ('security', ''),
        'record maintenance':           ('governance', 'records_of_processing'),
        'customer acceptance policy':   ('sector_specific', 'kyc_and_cdd'),
        'data disclosure restrictions': ('third_party', 'data_sharing'),
    }

    def test_all_four_resolve_through_the_alias_path(self):
        for wording, (topic, sub) in self.EXPECTED.items():
            with self.subTest(wording=wording):
                r = resolve_concept(wording, confidence=0.8)
                self.assertEqual(r.status, MATCHED, wording)
                self.assertEqual((r.topic, r.subcategory), (topic, sub))
                self.assertEqual(r.method, METHOD_ALIAS, wording)

    def test_all_four_land_on_valid_official_leaves(self):
        for wording in self.EXPECTED:
            with self.subTest(wording=wording):
                r = resolve_concept(wording, confidence=0.8)
                self.assertTrue(tx.is_valid(r.topic, r.subcategory or None))

    def test_none_of_them_would_now_become_a_suggestion(self):
        """The point of adding them: these stop reaching the review queue."""
        for wording in self.EXPECTED:
            with self.subTest(wording=wording):
                self.assertFalse(
                    resolve_concept(wording, confidence=0.8).is_unresolved)

    def test_casing_and_punctuation_variants_also_resolve(self):
        for wording in ('Cyber Risk Management', 'CYBER-RISK-MANAGEMENT',
                        'Record Maintenance', 'customer_acceptance_policy'):
            with self.subTest(wording=wording):
                self.assertEqual(resolve_concept(wording, confidence=0.8).status,
                                 MATCHED, wording)

    def test_the_model_wording_is_still_preserved(self):
        r = resolve_concept('cyber risk management', confidence=0.8)
        self.assertEqual(r.concept, 'cyber risk management')
        self.assertEqual(r.topic, 'security')

    def test_no_new_topic_was_created_for_any_of_them(self):
        for wording in self.EXPECTED:
            self.assertNotIn(tx.normalise_concept(wording).replace(' ', '_'),
                             TAXONOMY)
        self.assertEqual(len(TAXONOMY), 12)

    def test_the_speculative_concept_was_deliberately_not_aliased(self):
        """'legal effect of electronic transactions' appeared once, did not
        recur on a second run, and has no obvious official home. It stays
        unresolved so a human decides."""
        self.assertNotIn('legal effect of electronic transactions', ALIASES)
        r = resolve_concept('legal effect of electronic transactions',
                            confidence=0.8)
        self.assertTrue(r.is_unresolved)


class ExactMatchTests(SimpleTestCase):

    def test_official_topic_tag(self):
        r = resolve_concept('retention')
        self.assertEqual(r.status, MATCHED)
        self.assertEqual(r.topic, 'retention')
        self.assertEqual(r.subcategory, '')
        self.assertEqual(r.method, METHOD_EXACT)

    def test_official_leaf_path(self):
        r = resolve_concept('retention/retention_periods')
        self.assertEqual((r.status, r.topic, r.subcategory),
                         (MATCHED, 'retention', 'retention_periods'))
        self.assertEqual(r.method, METHOD_EXACT)
        self.assertEqual(r.leaf, 'retention/retention_periods')

    def test_bare_subcategory_tag(self):
        r = resolve_concept('regulator_notification')
        self.assertEqual((r.status, r.topic, r.subcategory),
                         (MATCHED, 'breach_management', 'regulator_notification'))
        self.assertEqual(r.method, METHOD_EXACT)

    def test_subcategory_supplied_separately_is_attached(self):
        r = resolve_concept('retention', subcategory='secure_disposal')
        self.assertEqual((r.topic, r.subcategory), ('retention', 'secure_disposal'))

    def test_invalid_subcategory_drops_but_keeps_topic(self):
        """A wrong subcategory must not sink an otherwise-correct topic —
        the topic is the load-bearing part."""
        r = resolve_concept('retention', subcategory='not_a_real_sub')
        self.assertEqual(r.status, MATCHED)
        self.assertEqual(r.topic, 'retention')
        self.assertEqual(r.subcategory, '')

    def test_subcategory_belonging_to_another_topic_is_not_attached(self):
        r = resolve_concept('retention', subcategory='access_control')
        self.assertEqual((r.topic, r.subcategory), ('retention', ''))


class AliasMatchTests(SimpleTestCase):
    """The three examples named in the brief, plus the casing/punctuation
    variants a model actually emits."""

    def test_storage_limitation(self):
        r = resolve_concept('storage limitation')
        self.assertEqual((r.status, r.topic), (MATCHED, 'retention'))
        self.assertEqual(r.method, METHOD_ALIAS)

    def test_data_retention(self):
        r = resolve_concept('data retention')
        self.assertEqual((r.status, r.topic), (MATCHED, 'retention'))
        self.assertEqual(r.method, METHOD_ALIAS)

    def test_data_storage_period(self):
        r = resolve_concept('data storage period')
        self.assertEqual((r.status, r.topic), (MATCHED, 'retention'))
        self.assertEqual(r.method, METHOD_ALIAS)

    def test_alias_is_case_and_punctuation_insensitive(self):
        for wording in ('Storage Limitation', 'STORAGE-LIMITATION',
                        'storage_limitation', '  Storage  Limitation!  '):
            with self.subTest(wording=wording):
                r = resolve_concept(wording)
                self.assertEqual(r.topic, 'retention', wording)

    def test_alias_can_carry_a_subcategory(self):
        r = resolve_concept('breach notification')
        self.assertEqual((r.topic, r.subcategory),
                         ('breach_management', 'regulator_notification'))

    def test_hyphenated_spelling_reaches_normalised_key(self):
        r = resolve_concept('automated decision-making')
        self.assertEqual(r.topic, 'data_subject_rights')
        self.assertEqual(r.method, METHOD_ALIAS)

    def test_original_wording_is_always_preserved(self):
        """What the model actually said is what makes duplicate suggestions
        detectable later without re-running it."""
        r = resolve_concept('Storage Limitation')
        self.assertEqual(r.concept, 'Storage Limitation')


class NormalizedMatchTests(SimpleTestCase):

    def test_human_label_resolves(self):
        r = resolve_concept('Security controls')
        self.assertEqual((r.status, r.topic), (MATCHED, 'security'))
        self.assertEqual(r.method, METHOD_NORMALIZED)

    def test_tag_with_spaces_resolves(self):
        r = resolve_concept('lawful basis')
        self.assertEqual((r.status, r.topic), (MATCHED, 'lawful_basis'))
        self.assertEqual(r.method, METHOD_NORMALIZED)

    def test_singular_plural_variation_resolves(self):
        r = resolve_concept('retention period')
        self.assertEqual((r.topic, r.subcategory), ('retention', 'retention_periods'))
        self.assertEqual(r.method, METHOD_NORMALIZED)

    def test_subcategory_label_resolves(self):
        r = resolve_concept('Secure disposal')
        self.assertEqual((r.topic, r.subcategory), ('retention', 'secure_disposal'))

    def test_normalise_concept_keeps_qualifying_words(self):
        """Dropping 'data' would turn 'data minimisation' into 'minimisation'
        and invite exactly the silent conflation this module refuses."""
        self.assertEqual(normalise_concept('Data  Minimisation!'), 'data minimisation')


class NoFitTests(SimpleTestCase):
    """'None of the existing topics fit' is a valid answer and must survive as
    one — not be recorded as a concept named 'n/a' that later gets proposed as
    an official topic."""

    def test_explicit_declines_are_unclassified(self):
        for wording in ('none', 'no suitable topic', 'N/A', 'unknown',
                        'unclassified', '', '   ', 'other'):
            with self.subTest(wording=wording):
                r = resolve_concept(wording)
                self.assertEqual(r.status, UNCLASSIFIED, wording)
                self.assertEqual(r.topic, '')

    def test_decline_is_not_unresolved(self):
        """UNCLASSIFIED must not reach the suggestion workflow — otherwise the
        review queue fills with topics called 'none'."""
        r = resolve_concept('none')
        self.assertFalse(r.is_unresolved)

    def test_low_confidence_is_unclassified_not_forced(self):
        r = resolve_concept('retention', confidence=0.12)
        self.assertEqual(r.status, UNCLASSIFIED)
        self.assertEqual(r.topic, '')
        self.assertIn('below floor', r.detail)

    def test_low_confidence_novel_concept_does_not_become_a_suggestion(self):
        r = resolve_concept('quantum-safe cryptographic agility', confidence=0.05)
        self.assertEqual(r.status, UNCLASSIFIED)
        self.assertFalse(r.is_unresolved)

    def test_confidence_at_floor_is_accepted(self):
        r = resolve_concept('retention', confidence=tx.MIN_CONCEPT_CONFIDENCE)
        self.assertEqual(r.status, MATCHED)


class UnresolvedTests(SimpleTestCase):

    def test_genuinely_new_concept_is_unresolved(self):
        r = resolve_concept('automated decision-making systems register',
                            confidence=0.8)
        self.assertEqual(r.status, UNRESOLVED)
        self.assertTrue(r.is_unresolved)
        self.assertEqual(r.topic, '')

    def test_unresolved_is_not_unclassified(self):
        r = resolve_concept('algorithmic impact assessment', confidence=0.8)
        self.assertEqual(r.status, UNRESOLVED)
        self.assertNotEqual(r.status, UNCLASSIFIED)

    def test_no_embedder_means_no_semantic_guessing(self):
        """Without an embed_fn the resolver stays deterministic — fuzziness is
        opt-in, never a silent default."""
        r = resolve_concept('protecting information assets', confidence=0.9)
        self.assertEqual(r.status, UNRESOLVED)
        self.assertEqual(r.method, METHOD_NONE)


class SemanticMatchTests(SimpleTestCase):

    def test_clears_threshold_and_margin(self):
        fn = make_embed_fn(('security', 'technical_measures'), best=0.90, runner=0.50)
        r = resolve_concept('protecting information assets', confidence=0.9, embed_fn=fn)
        self.assertEqual(r.status, MATCHED)
        self.assertEqual((r.topic, r.subcategory), ('security', 'technical_measures'))
        self.assertEqual(r.method, METHOD_SEMANTIC)

    def test_below_threshold_stays_unresolved(self):
        fn = make_embed_fn(('security', 'technical_measures'), best=0.60, runner=0.20)
        r = resolve_concept('protecting information assets', confidence=0.9, embed_fn=fn)
        self.assertEqual(r.status, UNRESOLVED)
        self.assertIn('did not clear', r.detail)

    def test_insufficient_margin_stays_unresolved(self):
        """A concept sitting between two topics is a real ambiguity. Assigning
        it to whichever scored 0.001 higher is a coin flip, not a decision."""
        fn = make_embed_fn(('security', 'technical_measures'), best=0.90, runner=0.89)
        r = resolve_concept('protecting information assets', confidence=0.9, embed_fn=fn)
        self.assertEqual(r.status, UNRESOLVED)

    def test_near_misses_are_returned_for_the_reviewer(self):
        fn = make_embed_fn(('security', 'technical_measures'), best=0.60, runner=0.20)
        r = resolve_concept('protecting information assets', confidence=0.9, embed_fn=fn)
        self.assertTrue(r.candidates)
        self.assertEqual(r.candidates[0][0], 'security')

    def test_embedder_failure_degrades_to_unresolved(self):
        def boom(_texts):
            raise RuntimeError('model not on disk')
        r = resolve_concept('protecting information assets', confidence=0.9, embed_fn=boom)
        self.assertEqual(r.status, UNRESOLVED)
        self.assertIn('unavailable', r.detail)

    def test_earlier_steps_win_before_semantic_runs(self):
        """Exact/alias/normalized are cheaper AND auditable, so semantic must
        never pre-empt them."""
        def boom(_texts):
            raise AssertionError('semantic step should not have been reached')
        r = resolve_concept('storage limitation', embed_fn=boom)
        self.assertEqual(r.method, METHOD_ALIAS)


class AmbiguityTests(SimpleTestCase):

    def test_ambiguous_normalised_form_refuses_to_guess(self):
        """Built by hand rather than found in the live taxonomy — today every
        name is unique, and this proves the refusal path works if that changes."""
        original = tx._MATCH_INDEX
        tx._MATCH_INDEX = dict(original)
        tx._MATCH_INDEX['shared wording'] = {('retention', ''), ('security', '')}
        try:
            r = resolve_concept('Shared Wording', confidence=0.9)
            self.assertEqual(r.status, UNRESOLVED)
            self.assertIn('ambiguous', r.detail)
            self.assertEqual(len(r.candidates), 2)
        finally:
            tx._MATCH_INDEX = original


class ResolveConceptsTests(SimpleTestCase):
    """The batch path the classifier will use. Multi-topic is the point, so the
    only thing collapsed is genuine duplication."""

    def test_multiple_distinct_topics_all_survive(self):
        out = resolve_concepts([
            {'concept': 'retention', 'confidence': 0.91},
            {'concept': 'security',  'confidence': 0.84},
        ])
        self.assertEqual([r.topic for r in out], ['retention', 'security'])
        self.assertTrue(all(r.is_matched for r in out))

    def test_two_wordings_of_one_topic_collapse(self):
        """'retention' and 'storage limitation' are ONE topic named twice.
        Storing both would double-count it in every downstream rollup."""
        out = resolve_concepts([
            {'concept': 'retention',         'confidence': 0.70},
            {'concept': 'storage limitation', 'confidence': 0.95},
        ])
        matched = [r for r in out if r.is_matched]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].topic, 'retention')

    def test_duplicate_keeps_the_higher_confidence_resolution(self):
        out = resolve_concepts([
            {'concept': 'retention',          'confidence': 0.70},
            {'concept': 'storage limitation', 'confidence': 0.95},
        ])
        self.assertAlmostEqual(out[0].confidence, 0.95)

    def test_bare_topic_is_absorbed_by_its_own_subcategory(self):
        """'retention' and 'retention/secure_disposal' are not two findings —
        the specific one says everything the general one said and more."""
        out = resolve_concepts([
            {'concept': 'retention',      'confidence': 0.9},
            {'concept': 'data disposal',  'confidence': 0.8},
        ])
        matched = [r for r in out if r.is_matched]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].leaf, 'retention/secure_disposal')

    def test_absorption_does_not_cross_topics(self):
        """A bare topic is only absorbed by ITS OWN subcategory, never by an
        unrelated topic that happens to be more specific."""
        out = resolve_concepts([
            {'concept': 'retention',      'confidence': 0.9},
            {'concept': 'access_control', 'confidence': 0.8},
        ])
        self.assertEqual({r.leaf for r in out if r.is_matched},
                         {'retention', 'security/access_control'})

    def test_distinct_leaves_under_one_topic_both_survive(self):
        out = resolve_concepts([
            {'concept': 'retention/retention_periods', 'confidence': 0.9},
            {'concept': 'retention/secure_disposal',   'confidence': 0.8},
        ])
        self.assertEqual(len([r for r in out if r.is_matched]), 2)

    def test_unresolved_and_matched_coexist(self):
        out = resolve_concepts([
            {'concept': 'retention', 'confidence': 0.9},
            {'concept': 'algorithmic accountability register', 'confidence': 0.8},
        ])
        self.assertEqual([r.status for r in out], [MATCHED, UNRESOLVED])

    def test_no_arbitrary_cap_on_topic_count(self):
        """v2 extraction caps free-text topics at 3. The controlled path must
        not inherit that limit — it was a prompt-shaping choice, not a rule
        about how many topics a provision can concern."""
        out = resolve_concepts([
            {'concept': t, 'confidence': 0.9} for t in list(TAXONOMY)[:6]
        ])
        self.assertEqual(len([r for r in out if r.is_matched]), 6)

    def test_malformed_items_are_skipped_not_fatal(self):
        out = resolve_concepts([None, 'retention', {'concept': 'security',
                                                    'confidence': 0.9}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].topic, 'security')

    def test_empty_input(self):
        self.assertEqual(resolve_concepts([]), [])
        self.assertEqual(resolve_concepts(None), [])


class ResolutionContractTests(SimpleTestCase):

    def test_resolution_is_immutable(self):
        r = resolve_concept('retention')
        with self.assertRaises(Exception):
            r.topic = 'security'

    def test_resolver_never_mutates_the_taxonomy(self):
        """The safety property the whole design rests on."""
        before = {t: sorted(b['subcategories']) for t, b in TAXONOMY.items()}
        for wording in ('retention', 'storage limitation', 'a brand new concept',
                        'none', 'Security Controls'):
            resolve_concept(wording, confidence=0.9)
        after = {t: sorted(b['subcategories']) for t, b in TAXONOMY.items()}
        self.assertEqual(before, after)
        self.assertEqual(TAXONOMY_VERSION, tx.fingerprint_of(TAXONOMY))

    def test_matched_always_carries_a_valid_leaf(self):
        for wording in ('retention', 'storage limitation', 'Security controls',
                        'regulator_notification', 'retention period', 'dsar'):
            with self.subTest(wording=wording):
                r = resolve_concept(wording, confidence=0.9)
                self.assertEqual(r.status, MATCHED)
                self.assertTrue(tx.is_valid(r.topic, r.subcategory or None),
                                f'{wording} -> {r.leaf}')

    def test_unmatched_never_carries_a_topic(self):
        for wording in ('none', 'a brand new concept', ''):
            with self.subTest(wording=wording):
                r = resolve_concept(wording, confidence=0.9)
                self.assertEqual(r.topic, '')
                self.assertEqual(r.leaf, '')
