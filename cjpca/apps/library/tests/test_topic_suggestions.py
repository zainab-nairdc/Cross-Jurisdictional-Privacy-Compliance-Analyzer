"""Phase 3 — human-governed taxonomy expansion and requirement review.

The property under test above all others:

    NO CODE PATH MAKES A TOPIC OFFICIAL.

A suggestion can be created, deduplicated, approved and patched, and the
official taxonomy is still untouched. `active` is reachable only after a human
has edited reasoning/taxonomy.py, and mark_active() verifies that by reading
the live taxonomy rather than trusting the database. Several tests below exist
purely to fail if that gate is ever weakened.

The second property: humans outrank the model. A reviewer's decision is stored
as provenance (assignment=HUMAN), not as a confidence of 1.0, so it survives
reclassification instead of being silently rebuilt away.
"""

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.library import suggestions as sug
from apps.library import topics as topic_service
from apps.library.models import (
    Document, Requirement, RequirementReference as RR, RequirementTopic as RT,
    TopicSuggestion as TS, TopicSuggestionEvidence as TSE,
)
from apps.library.tests.test_requirement_topics import (
    candidate, reply, stub, topic as topic_item,
)
from reasoning import taxonomy
from reasoning.taxonomy import resolve_concept


def _res(concept, confidence=0.8):
    return resolve_concept(concept, confidence=confidence)


class _Base(TestCase):
    def setUp(self):
        self.reg = Document.objects.create(
            name='Test Reg', doc_type=Document.REGULATION, jurisdiction='bahrain')
        self.req = Requirement.objects.create(
            regulation=self.reg, key='r1',
            text='The controller shall maintain a register of automated decisions.',
            article_ref='Article (12)', source_chunk_id='n12',
            source_quote='shall maintain a register of automated decisions')

    def _req(self, key, text='A rule about data.'):
        return Requirement.objects.create(
            regulation=self.reg, key=key, text=text,
            article_ref='Article (9)', source_chunk_id='n9',
            source_quote=text)


# ═══════════════════════════════════════════════════════════════════════════
# Suggestion intake — mostly about REFUSING
# ═══════════════════════════════════════════════════════════════════════════

class IntakeGateTests(_Base):

    def test_unresolved_concept_creates_a_suggestion(self):
        s, created = sug.ingest_unresolved(
            _res('algorithmic impact assessment'), requirement=self.req,
            evidence_quote='shall assess algorithmic impact')
        self.assertTrue(created)
        self.assertEqual(s.status, TS.SUGGESTED)
        self.assertEqual(s.proposed_slug, 'algorithmic_impact_assessment')
        self.assertEqual(s.occurrence_count, 1)

    def test_existing_concept_never_becomes_a_suggestion(self):
        """The taxonomy covers it — that is not a gap."""
        for wording in ('retention', 'storage limitation', 'Security controls',
                        'data storage period', 'dsar'):
            with self.subTest(wording=wording):
                s, _ = sug.ingest_unresolved(_res(wording), requirement=self.req)
                self.assertIsNone(s, wording)
        self.assertEqual(TS.objects.count(), 0)

    def test_no_fit_never_becomes_a_suggestion(self):
        for wording in ('none', 'n/a', 'unclassified', 'other', ''):
            with self.subTest(wording=wording):
                s, _ = sug.ingest_unresolved(_res(wording), requirement=self.req)
                self.assertIsNone(s)
        self.assertEqual(TS.objects.count(), 0)

    def test_low_confidence_never_becomes_a_suggestion(self):
        s, _ = sug.ingest_unresolved(
            _res('quantum key rotation policy', confidence=0.11),
            requirement=self.req)
        self.assertIsNone(s)
        self.assertEqual(TS.objects.count(), 0)

    def test_structural_artefacts_never_become_suggestions(self):
        """'definition' was observed in the Phase 2 dry run being proposed as a
        new official topic. It names a kind of text, not a compliance topic."""
        for wording in ('definition', 'definitions', 'provision', 'regulation',
                        'law', 'article', 'scope', 'interpretation'):
            with self.subTest(wording=wording):
                s, _ = sug.ingest_unresolved(_res(wording), requirement=self.req)
                self.assertIsNone(s, wording)
        self.assertEqual(TS.objects.count(), 0)

    def test_should_suggest_explains_its_refusal(self):
        ok, why = sug.should_suggest(_res('retention'))
        self.assertFalse(ok)
        self.assertIn('already covered', why)

    def test_evidence_is_recorded_from_real_source_text(self):
        s, _ = sug.ingest_unresolved(
            _res('algorithmic impact assessment'), requirement=self.req,
            evidence_quote=self.req.source_quote, chunk_node_id='n12')
        ev = s.evidence.get()
        self.assertEqual(ev.quote, self.req.source_quote)
        self.assertEqual(ev.requirement, self.req)
        self.assertEqual(ev.chunk_node_id, 'n12')
        self.assertEqual(ev.taxonomy_version, taxonomy.TAXONOMY_VERSION)


# ═══════════════════════════════════════════════════════════════════════════
# Deduplication — the synonym-spam guard
# ═══════════════════════════════════════════════════════════════════════════

class DeduplicationTests(_Base):

    def test_same_concept_twice_is_one_suggestion(self):
        sug.ingest_unresolved(_res('algorithmic impact assessment'),
                              requirement=self.req)
        s2, created = sug.ingest_unresolved(
            _res('algorithmic impact assessment'), requirement=self._req('r2'))
        self.assertFalse(created)
        self.assertEqual(TS.objects.count(), 1)
        self.assertEqual(s2.occurrence_count, 2)

    def test_casing_and_punctuation_variants_deduplicate(self):
        for wording in ('Algorithmic Impact Assessment',
                        'algorithmic-impact-assessment',
                        'ALGORITHMIC IMPACT ASSESSMENT'):
            sug.ingest_unresolved(_res(wording), requirement=self._req(wording[:8]))
        self.assertEqual(TS.objects.count(), 1)

    def test_the_four_retention_synonyms_do_not_become_four_suggestions(self):
        """The worked example from the brief. All four are the taxonomy's
        `retention`, so NONE of them should reach the queue at all."""
        for wording in ('Data Retention', 'Retention', 'Storage Limitation',
                        'Data Storage Period'):
            sug.ingest_unresolved(_res(wording), requirement=self._req(wording[:9]))
        self.assertEqual(TS.objects.count(), 0)

    def test_evidence_accumulates_without_inflating_the_count(self):
        """Re-running classification on the same requirement refreshes evidence
        rather than counting the same observation twice."""
        for _ in range(3):
            sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                  requirement=self.req)
        s = TS.objects.get()
        self.assertEqual(s.occurrence_count, 1)
        self.assertEqual(s.evidence.count(), 1)

    def test_distinct_requirements_each_add_evidence(self):
        for i in range(4):
            sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                  requirement=self._req(f'k{i}'))
        s = TS.objects.get()
        self.assertEqual(s.occurrence_count, 4)

    def test_confidence_is_the_maximum_observed(self):
        sug.ingest_unresolved(_res('algorithmic impact assessment', 0.4),
                              requirement=self._req('a'))
        sug.ingest_unresolved(_res('algorithmic impact assessment', 0.92),
                              requirement=self._req('b'))
        self.assertAlmostEqual(TS.objects.get().confidence, 0.92)

    def test_semantic_dedup_folds_a_near_synonym(self):
        sug.ingest_unresolved(_res('algorithmic impact assessment'),
                              requirement=self.req)

        def embed(texts):
            # probe aligned with the single open suggestion
            return [[1.0, 0.0]] + [[0.95, (1 - 0.95 ** 2) ** 0.5]
                                   for _ in texts[1:]]

        s, created = sug.ingest_unresolved(
            _res('algorithmic effect evaluation'),
            requirement=self._req('r2'), embed_fn=embed)
        self.assertFalse(created)
        self.assertEqual(TS.objects.count(), 1)

    def test_a_rejected_suggestion_does_not_block_a_fresh_one(self):
        """Rejection judges what was known then, not forever."""
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        sug.reject(s)
        s2, created = sug.ingest_unresolved(
            _res('algorithmic impact assessment'), requirement=self._req('r2'))
        self.assertTrue(created)
        self.assertNotEqual(s2.pk, s.pk)


class OccurrenceThresholdTests(_Base):

    def test_threshold_is_configurable_not_hard_coded(self):
        with self.settings(TOPIC_SUGGESTION_THRESHOLD=3):
            self.assertEqual(sug.occurrence_threshold(), 3)

    def test_default_threshold(self):
        self.assertEqual(sug.occurrence_threshold(),
                         sug.DEFAULT_OCCURRENCE_THRESHOLD)

    def test_reaching_the_threshold_promotes_nothing(self):
        """Count changes queue ORDER and nothing else. A human still approves."""
        with self.settings(TOPIC_SUGGESTION_THRESHOLD=2):
            for i in range(5):
                sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                      requirement=self._req(f'k{i}'))
            s = TS.objects.get()
            self.assertGreaterEqual(s.occurrence_count,
                                    sug.occurrence_threshold())
            self.assertEqual(s.status, TS.SUGGESTED)

    def test_queue_orders_high_signal_first(self):
        for i in range(3):
            sug.ingest_unresolved(_res('concept alpha'), requirement=self._req(f'a{i}'))
        sug.ingest_unresolved(_res('concept beta'), requirement=self._req('b0'))
        self.assertEqual([s.proposed_name for s in sug.queue()],
                         ['concept alpha', 'concept beta'])


# ═══════════════════════════════════════════════════════════════════════════
# Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class LifecycleTests(_Base):

    def setUp(self):
        super().setUp()
        self.s, _ = sug.ingest_unresolved(
            _res('algorithmic impact assessment'), requirement=self.req,
            evidence_quote='shall assess algorithmic impact')

    def test_start_review(self):
        sug.start_review(self.s, note='looking at it')
        self.assertEqual(self.s.status, TS.UNDER_REVIEW)
        self.assertIsNotNone(self.s.reviewed_at)

    def test_approve_moves_to_pending_release_not_active(self):
        sug.approve(self.s)
        self.assertEqual(self.s.status, TS.APPROVED_PENDING_RELEASE)
        self.assertNotEqual(self.s.status, TS.ACTIVE)

    def test_approve_generates_a_patch(self):
        sug.approve(self.s)
        self.assertIn('PROPOSED TAXONOMY CHANGE', self.s.proposed_patch)
        self.assertIn('algorithmic_impact_assessment', self.s.proposed_patch)

    def test_approve_records_the_expected_next_version(self):
        sug.approve(self.s)
        self.assertTrue(self.s.expected_taxonomy_version)
        self.assertNotEqual(self.s.expected_taxonomy_version,
                            taxonomy.TAXONOMY_VERSION)

    def test_reviewer_may_edit_before_approving(self):
        """The model's naming is a starting point, not a specification."""
        sug.approve(self.s, name='Automated decision-making',
                    parent_topic='governance', subcategory='adm_register')
        self.assertEqual(self.s.proposed_name, 'Automated decision-making')
        self.assertEqual(self.s.parent_topic, 'governance')
        self.assertEqual(self.s.target_leaf, 'governance/adm_register')

    def test_cannot_approve_something_the_taxonomy_already_has(self):
        s = sug.create_manual_suggestion(name='Brand New Thing')
        s.parent_topic = 'retention'
        s.proposed_subcategory = 'secure_disposal'
        s.save()
        with self.assertRaises(ValueError) as ctx:
            sug.approve(s)
        self.assertIn('merge into it', str(ctx.exception))

    def test_reject(self):
        sug.reject(self.s, note='really just security')
        self.assertEqual(self.s.status, TS.REJECTED)
        self.assertEqual(self.s.reviewer_note, 'really just security')

    def test_reject_detaches_but_does_not_delete_assignments(self):
        """The model DID raise that concept about that requirement. Rejecting
        the proposal does not un-happen it."""
        row = RT.objects.create(requirement=self.req, topic='',
                                model_concept='algorithmic impact assessment',
                                assignment=RT.SUGGESTED, suggestion=self.s)
        sug.reject(self.s)
        row.refresh_from_db()
        self.assertIsNone(row.suggestion)
        self.assertTrue(RT.objects.filter(pk=row.pk).exists())

    def test_merge_into_existing_topic(self):
        s2, converted = sug.merge_into_topic(self.s, 'governance',
                                             'records_of_processing')
        self.assertEqual(s2.status, TS.MERGED)
        self.assertEqual(s2.merged_into_topic, 'governance')

    def test_merge_into_topic_repoints_assignments_as_human(self):
        """The reviewer's judgement is recorded where the data is read — and
        therefore survives reclassification."""
        RT.objects.create(requirement=self.req, topic='',
                          model_concept='algorithmic impact assessment',
                          assignment=RT.SUGGESTED, suggestion=self.s)
        _, converted = sug.merge_into_topic(self.s, 'governance',
                                            'records_of_processing')
        self.assertEqual(converted, 1)
        row = RT.objects.get(requirement=self.req)
        self.assertEqual(row.topic, 'governance')
        self.assertEqual(row.assignment, RT.HUMAN)
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['governance'])

    def test_merge_into_a_non_official_topic_is_refused(self):
        with self.assertRaises(ValueError):
            sug.merge_into_topic(self.s, 'not_a_real_topic')

    def test_merge_into_another_suggestion(self):
        other, _ = sug.ingest_unresolved(_res('automated decision registers'),
                                         requirement=self._req('r2'))
        merged, target = sug.merge_into_suggestion(self.s, other)
        self.assertEqual(merged.status, TS.MERGED)
        self.assertEqual(merged.merged_into_suggestion, other)
        self.assertEqual(target.occurrence_count, 2)

    def test_cannot_merge_a_suggestion_into_itself(self):
        with self.assertRaises(ValueError):
            sug.merge_into_suggestion(self.s, self.s)


# ═══════════════════════════════════════════════════════════════════════════
# THE RELEASE GATE — the safety property of this whole phase
# ═══════════════════════════════════════════════════════════════════════════

class ReleaseGateTests(_Base):

    def setUp(self):
        super().setUp()
        self.s, _ = sug.ingest_unresolved(
            _res('algorithmic impact assessment'), requirement=self.req)

    def test_mark_active_refuses_until_the_taxonomy_actually_contains_it(self):
        sug.approve(self.s)
        with self.assertRaises(ValueError) as ctx:
            sug.mark_active(self.s)
        self.assertIn('not in the official taxonomy', str(ctx.exception))
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, TS.APPROVED_PENDING_RELEASE)

    def test_mark_active_refuses_from_any_other_status(self):
        for status in (TS.SUGGESTED, TS.UNDER_REVIEW, TS.REJECTED, TS.MERGED):
            with self.subTest(status=status):
                self.s.status = status
                self.s.save()
                with self.assertRaises(ValueError):
                    sug.mark_active(self.s)

    def test_mark_active_succeeds_once_the_topic_really_exists(self):
        """Simulates the human having edited and committed taxonomy.py."""
        sug.approve(self.s, parent_topic='governance', subcategory='adm_register')
        original = taxonomy.TAXONOMY['governance']['subcategories'].copy()
        taxonomy.TAXONOMY['governance']['subcategories']['adm_register'] = 'ADM register'
        try:
            sug.mark_active(self.s)
            self.assertEqual(self.s.status, TS.ACTIVE)
            self.assertTrue(self.s.is_official)
        finally:
            taxonomy.TAXONOMY['governance']['subcategories'] = original

    def test_is_official_reads_the_taxonomy_not_the_status(self):
        """The database cannot make a topic official, so the database is not
        what gets asked."""
        self.s.status = TS.ACTIVE
        self.s.save()
        self.assertFalse(self.s.is_official)

    def test_approving_does_not_touch_the_taxonomy(self):
        before = {t: sorted(b['subcategories'])
                  for t, b in taxonomy.TAXONOMY.items()}
        sug.approve(self.s)
        after = {t: sorted(b['subcategories'])
                 for t, b in taxonomy.TAXONOMY.items()}
        self.assertEqual(before, after)
        self.assertEqual(taxonomy.TAXONOMY_VERSION, taxonomy.fingerprint_of(taxonomy.TAXONOMY))

    def test_no_service_call_mutates_the_taxonomy_source(self):
        from pathlib import Path
        source = Path(taxonomy.__file__)
        before = source.read_bytes()
        s2, _ = sug.ingest_unresolved(_res('another novel concept'),
                                      requirement=self._req('r9'))
        sug.start_review(s2)
        sug.approve(s2)
        sug.build_patch(s2)
        sug.reject(self.s)
        self.assertEqual(source.read_bytes(), before,
                         'reasoning/taxonomy.py was modified by a service call')


class PatchGenerationTests(_Base):

    def test_patch_for_a_new_top_level_topic(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        sug.approve(s)
        patch = s.proposed_patch
        self.assertIn('Add a new top-level topic', patch)
        self.assertIn('"label"', patch)
        self.assertIn('subcategories', patch)
        self.assertIn('TAXONOMY_LINEAGE', patch)
        self.assertIn('LINEAGE_ADDITIVE', patch)

    def test_patch_for_a_new_subcategory(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        sug.approve(s, parent_topic='governance', subcategory='adm_register')
        self.assertIn('Add a subcategory under the existing "governance"',
                      s.proposed_patch)

    def test_patch_predicts_the_resulting_version(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        sug.approve(s)
        # Labels are part of the v2 fingerprint, so the prediction must be
        # built from the same labels the patch text writes — otherwise the
        # predicted version would not match the file once applied.
        self.assertIn(sug.predicted_version(s), s.proposed_patch)
        self.assertEqual(s.expected_taxonomy_version, sug.predicted_version(s))

    def test_top_level_patch_no_longer_invents_a_placeholder_subcategory(self):
        """The v1 fingerprint hashed leaves only, so a topic with no
        subcategories would not have changed the version — the patch had to
        invent a "general" leaf to force one. v2 hashes topics too, so the
        placeholder is gone."""
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        sug.approve(s)
        self.assertNotIn('"general": "General"', s.proposed_patch)
        self.assertIn('"subcategories": {}', s.proposed_patch)

    def test_a_topic_with_no_subcategories_still_changes_the_version(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        sug.approve(s)
        self.assertNotEqual(s.expected_taxonomy_version,
                            taxonomy.TAXONOMY_VERSION)

    def test_patch_includes_observed_wordings_as_aliases(self):
        """Without these the same phrasing returns as a fresh suggestion the
        moment the topic exists."""
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        sug.ingest_unresolved(_res('Algorithmic Impact Assessments'),
                              requirement=self._req('r2'))
        s.refresh_from_db()
        sug.approve(s)
        self.assertIn('ALIASES', s.proposed_patch)

    def test_patch_is_a_string_not_an_action(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        self.assertIsInstance(sug.build_patch(s), str)
        self.assertEqual(TS.objects.get(pk=s.pk).status, TS.SUGGESTED)


class FingerprintPredictionTests(SimpleTestCase):

    def test_no_extra_leaves_reproduces_the_current_version(self):
        self.assertEqual(taxonomy.fingerprint_with([]), taxonomy.TAXONOMY_VERSION)
        self.assertEqual(taxonomy.fingerprint_with(), taxonomy.TAXONOMY_VERSION)

    def test_adding_a_leaf_changes_the_fingerprint(self):
        self.assertNotEqual(taxonomy.fingerprint_with(['newtopic/newleaf']),
                            taxonomy.TAXONOMY_VERSION)

    def test_prediction_is_deterministic(self):
        self.assertEqual(taxonomy.fingerprint_with(['a/b']),
                         taxonomy.fingerprint_with(['a/b']))

    def test_prediction_does_not_mutate_the_taxonomy(self):
        before = len(taxonomy.TAXONOMY)
        taxonomy.fingerprint_with(['brand_new/leaf'])
        self.assertEqual(len(taxonomy.TAXONOMY), before)
        self.assertEqual(taxonomy.TAXONOMY_VERSION, taxonomy.fingerprint_of(taxonomy.TAXONOMY))


# ═══════════════════════════════════════════════════════════════════════════
# Manual topic creation — the taxonomy is not owned by the model
# ═══════════════════════════════════════════════════════════════════════════

class ManualCreationTests(_Base):

    def test_manual_top_level_topic(self):
        s = sug.create_manual_suggestion(
            name='Electronic transactions', reason='e-signature validity')
        self.assertEqual(s.origin, TS.HUMAN)
        self.assertEqual(s.status, TS.SUGGESTED)
        self.assertEqual(s.proposed_slug, 'electronic_transactions')

    def test_manual_subcategory_under_an_existing_topic(self):
        s = sug.create_manual_suggestion(
            name='ADM register', parent_topic='governance',
            subcategory='adm_register')
        self.assertEqual(s.parent_topic, 'governance')
        self.assertEqual(s.target_leaf, 'governance/adm_register')

    def test_manual_creation_still_needs_approval_and_release(self):
        """The LLM is a suggestion mechanism, not the owner — but a human
        proposing directly does not skip the boundary either."""
        s = sug.create_manual_suggestion(name='Electronic transactions')
        self.assertNotEqual(s.status, TS.ACTIVE)
        sug.approve(s)
        self.assertEqual(s.status, TS.APPROVED_PENDING_RELEASE)
        with self.assertRaises(ValueError):
            sug.mark_active(s)

    def test_manual_creation_rejects_an_existing_topic(self):
        with self.assertRaises(ValueError):
            sug.create_manual_suggestion(name='retention')

    def test_manual_creation_rejects_an_existing_subcategory(self):
        with self.assertRaises(ValueError):
            sug.create_manual_suggestion(
                name='Secure disposal', parent_topic='retention',
                subcategory='secure_disposal')

    def test_manual_creation_rejects_an_unknown_parent(self):
        with self.assertRaises(ValueError):
            sug.create_manual_suggestion(name='Thing', parent_topic='nonsense')

    def test_manual_creation_rejects_an_empty_name(self):
        for bad in ('', '   ', '!!!'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    sug.create_manual_suggestion(name=bad)

    def test_manual_creation_rejects_a_duplicate_open_suggestion(self):
        sug.create_manual_suggestion(name='Electronic transactions')
        with self.assertRaises(ValueError):
            sug.create_manual_suggestion(name='electronic transactions')


# ═══════════════════════════════════════════════════════════════════════════
# Human review of requirement topics
# ═══════════════════════════════════════════════════════════════════════════

class HumanAssignmentTests(_Base):

    def test_add_human_topic(self):
        row = topic_service.add_human_topic(self.req, 'governance',
                                            'records_of_processing', note='mine')
        self.assertEqual(row.assignment, RT.HUMAN)
        self.assertEqual(row.resolution_method, RT.HUMAN_M)
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['governance'])

    def test_human_provenance_not_a_fake_confidence(self):
        """Confidence 1.0 would be a lie about a measurement AND would be
        rebuilt away by the next run. Provenance is the mechanism."""
        row = topic_service.add_human_topic(self.req, 'governance')
        self.assertEqual(row.confidence, 0.0)
        self.assertEqual(row.assignment, RT.HUMAN)

    def test_human_topic_must_be_official(self):
        with self.assertRaises(ValueError):
            topic_service.add_human_topic(self.req, 'invented_topic')

    def test_human_assignment_overrides_a_model_assignment(self):
        topic_service.classify_and_store(
            self.req, chat=stub(reply([topic_item('security', conf=0.72)])),
            dry_run=False)
        topic_service.add_human_topic(self.req, 'governance')
        topic_service.remove_topic(
            self.req, RT.objects.get(requirement=self.req, topic='security').pk)
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['governance'])

    def test_human_assignment_survives_reclassification(self):
        topic_service.add_human_topic(self.req, 'governance')
        topic_service.classify_and_store(
            self.req, chat=stub(reply([topic_item('security', conf=0.9)])),
            dry_run=False)
        topics = set(RT.objects.filter(requirement=self.req)
                     .values_list('topic', flat=True))
        self.assertIn('governance', topics)
        self.assertEqual(
            RT.objects.get(requirement=self.req, topic='governance').assignment,
            RT.HUMAN)

    def test_multiple_topics_remain_possible_after_human_edits(self):
        topic_service.add_human_topic(self.req, 'governance')
        topic_service.add_human_topic(self.req, 'security', 'access_control')
        self.req.refresh_from_db()
        self.assertEqual(sorted(self.req.topics), ['governance', 'security'])

    def test_removing_one_topic_does_not_remove_others(self):
        topic_service.add_human_topic(self.req, 'governance')
        row = topic_service.add_human_topic(self.req, 'security')
        topic_service.remove_topic(self.req, row.pk)
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['governance'])

    def test_remove_a_missing_assignment_is_harmless(self):
        self.assertFalse(topic_service.remove_topic(self.req, 999999))

    def test_mark_unclassified_clears_topics_and_records_the_decision(self):
        topic_service.add_human_topic(self.req, 'governance')
        topic_service.mark_unclassified(self.req, note='commencement clause')
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, [])
        row = RT.objects.get(requirement=self.req)
        self.assertEqual(row.assignment, RT.HUMAN)
        self.assertEqual(row.topic, '')

    def test_human_edits_never_touch_extraction_fields(self):
        before = (self.req.text, self.req.source_quote, self.req.key,
                  self.req.article_ref)
        topic_service.add_human_topic(self.req, 'governance')
        topic_service.mark_unclassified(self.req)
        self.req.refresh_from_db()
        self.assertEqual((self.req.text, self.req.source_quote, self.req.key,
                          self.req.article_ref), before)


class SuggestionIngestionFromClassificationTests(_Base):

    def test_classification_routes_unresolved_concepts_into_the_queue(self):
        topic_service.classify_and_store(
            self.req,
            chat=stub(reply([topic_item('governance')],
                            [candidate('algorithmic impact assessment')])),
            dry_run=False)
        self.assertEqual(TS.objects.count(), 1)
        row = RT.objects.get(requirement=self.req, assignment=RT.SUGGESTED)
        self.assertIsNotNone(row.suggestion)

    def test_dry_run_creates_no_suggestions(self):
        topic_service.classify_and_store(
            self.req, chat=stub(reply([], [candidate('novel concept')])),
            dry_run=True)
        self.assertEqual(TS.objects.count(), 0)

    def test_reclassification_does_not_inflate_occurrence_count(self):
        payload = reply([], [candidate('algorithmic impact assessment')])
        for _ in range(3):
            topic_service.classify_and_store(self.req, chat=stub(payload),
                                             dry_run=False)
        self.assertEqual(TS.objects.get().occurrence_count, 1)

    def test_a_suggestion_failure_does_not_lose_the_classification(self):
        import apps.library.topics as mod
        original = mod._ingest_suggestions
        mod._ingest_suggestions = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('queue down'))
        self.addCleanup(setattr, mod, '_ingest_suggestions', original)
        try:
            topic_service.classify_and_store(
                self.req, chat=stub(reply([topic_item('governance')])),
                dry_run=False)
        except RuntimeError:
            pass
        self.assertTrue(RT.objects.filter(requirement=self.req).exists())


# ═══════════════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════════════

class ViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('rev', password='x')
        self.client.force_login(self.user)
        self.reg = Document.objects.create(
            name='UI Reg', doc_type=Document.REGULATION, jurisdiction='bahrain')
        self.req = Requirement.objects.create(
            regulation=self.reg, key='u1',
            text='REs shall put in place a Risk Management framework for '
                 'Outsourcing of IT Services.',
            article_ref='Article (17)', source_chunk_id='n17',
            source_quote='shall put in place a Risk Management framework')

    def test_requirement_list_renders(self):
        r = self.client.get(reverse('library-requirements'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'REs shall put in place')

    def test_requirement_detail_shows_all_topics(self):
        """The brief's example: governance AND third_party must both show."""
        topic_service.classify_and_store(
            self.req,
            chat=stub(reply([topic_item('governance', conf=0.95),
                             topic_item('third_party', 'vendor_due_diligence',
                                        conf=0.87)])),
            dry_run=False)
        r = self.client.get(reverse('library-requirement-detail',
                                    args=[self.req.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Governance')
        self.assertContains(r, 'Vendor due diligence')

    def test_requirement_detail_shows_reference_states(self):
        RR.objects.create(requirement=self.req, ref_text='Article 31',
                          ref_kind=RR.ARTICLE, ref_number='31',
                          status=RR.RESOLVED, scope=RR.INTERNAL,
                          target_chunk_id='n31', confidence=0.95)
        RR.objects.create(requirement=self.req, ref_text='Articles 31 to 35',
                          ref_kind=RR.ARTICLE, ref_number='31-35',
                          status=RR.AMBIGUOUS, scope=RR.INTERNAL,
                          candidates=['n31', 'n32', 'n33', 'n34', 'n35'],
                          confidence=0.9)
        RR.objects.create(requirement=self.req, ref_text='Law No. 77 of 1999',
                          ref_kind=RR.LAW, status=RR.UNRESOLVED,
                          scope=RR.EXTERNAL)
        r = self.client.get(reverse('library-requirement-detail',
                                    args=[self.req.pk]))
        self.assertContains(r, 'resolved')
        self.assertContains(r, 'ambiguous')
        self.assertContains(r, 'unresolved')
        self.assertContains(r, 'External')

    def test_ambiguous_reference_lists_every_candidate(self):
        RR.objects.create(requirement=self.req, ref_text='Articles 31 to 35',
                          ref_kind=RR.ARTICLE, ref_number='31-35',
                          status=RR.AMBIGUOUS, scope=RR.INTERNAL,
                          candidates=['n31', 'n32', 'n33', 'n34', 'n35'])
        r = self.client.get(reverse('library-requirement-detail',
                                    args=[self.req.pk]))
        self.assertContains(r, '5 candidate targets')

    def test_add_topic_action(self):
        self.client.post(reverse('library-requirement-topics', args=[self.req.pk]),
                         {'action': 'add', 'leaf': 'governance/dpia_and_risk'})
        row = RT.objects.get(requirement=self.req)
        self.assertEqual(row.assignment, RT.HUMAN)
        self.assertEqual(row.subcategory, 'dpia_and_risk')

    def test_add_invalid_topic_is_reported_not_stored(self):
        r = self.client.post(
            reverse('library-requirement-topics', args=[self.req.pk]),
            {'action': 'add', 'leaf': 'not_a_topic'}, follow=True)
        self.assertEqual(RT.objects.count(), 0)
        self.assertContains(r, 'not an official taxonomy leaf')

    def test_remove_topic_action(self):
        row = topic_service.add_human_topic(self.req, 'governance')
        self.client.post(reverse('library-requirement-topics', args=[self.req.pk]),
                         {'action': 'remove', 'assignment_id': row.pk})
        self.assertFalse(RT.objects.filter(pk=row.pk).exists())

    def test_suggestion_queue_renders(self):
        sug.ingest_unresolved(_res('algorithmic impact assessment'),
                              requirement=self.req)
        r = self.client.get(reverse('library-topic-suggestions'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'algorithmic impact assessment')

    def test_suggestion_detail_shows_evidence(self):
        s, _ = sug.ingest_unresolved(
            _res('algorithmic impact assessment'), requirement=self.req,
            evidence_quote='shall put in place a Risk Management framework')
        r = self.client.get(reverse('library-topic-suggestion-detail', args=[s.pk]))
        self.assertContains(r, 'Risk Management framework')

    def test_approve_via_ui_does_not_make_it_official(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        before = {t: sorted(b['subcategories'])
                  for t, b in taxonomy.TAXONOMY.items()}
        r = self.client.post(
            reverse('library-topic-suggestion-action', args=[s.pk]),
            {'action': 'approve', 'name': 'Automated decision-making'},
            follow=True)
        s.refresh_from_db()
        self.assertEqual(s.status, TS.APPROVED_PENDING_RELEASE)
        self.assertEqual({t: sorted(b['subcategories'])
                          for t, b in taxonomy.TAXONOMY.items()}, before)
        self.assertContains(r, 'NOT official yet')

    def test_mark_active_via_ui_is_refused_before_release(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        sug.approve(s)
        r = self.client.post(
            reverse('library-topic-suggestion-action', args=[s.pk]),
            {'action': 'mark_active'}, follow=True)
        s.refresh_from_db()
        self.assertEqual(s.status, TS.APPROVED_PENDING_RELEASE)
        self.assertContains(r, 'not in the official taxonomy')

    def test_merge_into_topic_via_ui(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        self.client.post(reverse('library-topic-suggestion-action', args=[s.pk]),
                         {'action': 'merge_topic', 'leaf': 'governance'})
        s.refresh_from_db()
        self.assertEqual(s.status, TS.MERGED)
        self.assertEqual(s.merged_into_topic, 'governance')

    def test_reject_via_ui(self):
        s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                     requirement=self.req)
        self.client.post(reverse('library-topic-suggestion-action', args=[s.pk]),
                         {'action': 'reject', 'note': 'really security'})
        s.refresh_from_db()
        self.assertEqual(s.status, TS.REJECTED)

    def test_manual_creation_via_ui(self):
        self.client.post(reverse('library-topic-suggestion-create'),
                         {'name': 'Electronic transactions',
                          'reason': 'e-signature validity'})
        s = TS.objects.get()
        self.assertEqual(s.origin, TS.HUMAN)
        self.assertEqual(s.status, TS.SUGGESTED)

    def test_manual_creation_of_an_existing_topic_is_refused(self):
        r = self.client.post(reverse('library-topic-suggestion-create'),
                             {'name': 'retention'}, follow=True)
        self.assertEqual(TS.objects.count(), 0)
        self.assertContains(r, 'already exists')

    def test_no_taxonomy_option_list_is_capped_at_twelve(self):
        """The pickers are built from TAXONOMY at request time, so they grow
        the moment a topic is released. Nothing assumes twelve of anything."""
        from apps.library.review_views import _taxonomy_options
        options = _taxonomy_options()
        top_level = [o for o in options if o['depth'] == 0]
        self.assertEqual(len(top_level), len(taxonomy.TAXONOMY))
        self.assertEqual(len(options), len(taxonomy.TAXONOMY) + 44)


class CommandTests(TestCase):

    def setUp(self):
        self.reg = Document.objects.create(
            name='Cmd Reg', doc_type=Document.REGULATION, jurisdiction='bahrain')
        self.req = Requirement.objects.create(
            regulation=self.reg, key='c1', text='A rule.',
            article_ref='Article (1)', source_chunk_id='n1', source_quote='q')
        self.s, _ = sug.ingest_unresolved(_res('algorithmic impact assessment'),
                                          requirement=self.req)

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('taxonomy_apply', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_prints_the_patch_without_writing_taxonomy(self):
        from pathlib import Path
        sug.approve(self.s)
        source = Path(taxonomy.__file__)
        before = source.read_bytes()
        out = self._run(str(self.s.pk))
        self.assertIn('PROPOSED TAXONOMY CHANGE', out)
        self.assertIn('was NOT modified', out)
        self.assertEqual(source.read_bytes(), before)

    def test_refuses_to_write_a_file_named_taxonomy_py(self, ):
        sug.approve(self.s)
        out = self._run(str(self.s.pk), '--out', 'taxonomy.py')
        self.assertIn('Refusing to write', out)

    def test_list_shows_pending_release(self):
        sug.approve(self.s)
        self.assertIn('Awaiting taxonomy release', self._run('--list'))

    def test_mark_active_is_refused_before_release(self):
        sug.approve(self.s)
        out = self._run(str(self.s.pk), '--mark-active')
        self.assertIn('Refused', out)
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, TS.APPROVED_PENDING_RELEASE)

    def test_unknown_id_reports_cleanly(self):
        self.assertIn('No suggestion with id 999999', self._run('999999'))


class NoChunkTagChangeTests(TestCase):
    """Phase 3 must leave the chunk pipeline entirely alone."""

    def test_chunk_tags_schema_is_untouched(self):
        from retrieval import bm25_store
        self.assertIn('node_id           TEXT PRIMARY KEY',
                      bm25_store._CREATE_TAGS_TABLE)

    def test_no_suggestion_path_writes_chunk_tags(self):
        from retrieval import bm25_store
        called = []
        original = bm25_store.upsert_chunk_tags
        bm25_store.upsert_chunk_tags = lambda rows: called.append(rows)
        try:
            reg = Document.objects.create(name='R', doc_type=Document.REGULATION)
            req = Requirement.objects.create(regulation=reg, key='k', text='t',
                                             source_chunk_id='n', source_quote='q')
            s, _ = sug.ingest_unresolved(_res('novel concept'), requirement=req)
            sug.approve(s)
            topic_service.add_human_topic(req, 'governance')
        finally:
            bm25_store.upsert_chunk_tags = original
        self.assertEqual(called, [])
