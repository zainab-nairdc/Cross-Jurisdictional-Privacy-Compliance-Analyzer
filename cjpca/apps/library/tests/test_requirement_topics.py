"""Phase 2 — multi-topic requirement classification.

The property under test throughout: a requirement may carry ZERO, ONE, or
SEVERAL topics, and nothing in the schema, the service, or the classifier
assumes one. Several tests below exist specifically to fail if a single-label
assumption creeps back in.

Two distinctions that must not collapse:

  matched vs suggested   — an official topic versus a real concept the
                           taxonomy lacks. The second is the input to human
                           review and must never be forced into the first.
  suggested vs unclassified — a taxonomy gap versus nothing to classify.
                           Merging them either buries gaps or floods review.

The model is stubbed everywhere: these test the resolution, ranking and
persistence contract, not Ollama.
"""

from django.test import SimpleTestCase, TestCase

from apps.library.models import (
    Document, Requirement, RequirementTopic as RT,
)
from apps.library.topics import (
    apply_classification, classify_and_store,
    classify_requirements_for_regulation, plan_assignments, sync_topics_mirror,
)
from reasoning import taxonomy
from reasoning.requirement_classify import (
    CLASSIFIER_VERSION, MAX_TOPICS, classify_requirement,
)


def stub(payload, *, fail=False):
    """A chat callable returning a fixed model reply."""
    def _chat(_prompt, _model=None):
        if fail:
            raise RuntimeError('ollama unreachable')
        return payload
    return _chat


def topic(concept, sub='', conf=0.9, evidence='because the text says so'):
    return {'concept': concept, 'subcategory': sub,
            'confidence': conf, 'evidence': evidence}


def candidate(concept, conf=0.8, **kw):
    return {'concept': concept, 'confidence': conf,
            'reason': kw.get('reason', 'a concept'),
            'why_existing_topics_are_insufficient': kw.get('why', 'none fit'),
            'evidence': kw.get('evidence', 'quoted phrase')}


def reply(topics=(), candidates=()):
    return {'topics': list(topics), 'new_topic_candidates': list(candidates)}


class _Base(TestCase):
    def setUp(self):
        self.reg = Document.objects.create(
            name='Test Reg', doc_type=Document.REGULATION, jurisdiction='bahrain')
        self.req = Requirement.objects.create(
            regulation=self.reg, key='r1',
            text='A controller shall retain personal data only for as long as '
                 'necessary and shall implement appropriate technical and '
                 'organisational measures to protect it.',
            article_ref='Article (12)', source_chunk_id='n12',
            source_quote='Personal data shall be retained securely for no '
                         'longer than five years.')

    def classify(self, payload, **kw):
        return classify_and_store(self.req, chat=stub(payload),
                                  dry_run=False, **kw)

    def rows(self):
        return list(self.req.topic_assignments.order_by('rank', 'id'))


# ═══════════════════════════════════════════════════════════════════════════
# A-C: cardinality
# ═══════════════════════════════════════════════════════════════════════════

class CardinalityTests(_Base):

    def test_a_one_requirement_one_topic(self):
        self.classify(reply([topic('retention')]))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].topic, 'retention')
        self.assertEqual(rows[0].assignment, RT.MATCHED)

    def test_b_one_requirement_multiple_topics(self):
        """The worked example from the brief. Both topics are genuine; naming
        only one would lose half of what the provision says."""
        self.classify(reply([topic('retention', conf=0.91),
                             topic('security', conf=0.84)]))
        self.assertEqual([r.topic for r in self.rows()], ['retention', 'security'])

    def test_u_more_than_one_topic_is_actually_persisted(self):
        self.classify(reply([topic('retention'), topic('security')]))
        self.assertEqual(
            RT.objects.filter(requirement=self.req,
                              assignment=RT.MATCHED).count(), 2)

    def test_c_three_legitimate_topics(self):
        self.classify(reply([topic('retention', conf=0.9),
                             topic('security', conf=0.85),
                             topic('cross_border', conf=0.8)]))
        self.assertEqual({r.topic for r in self.rows()},
                         {'retention', 'security', 'cross_border'})

    def test_m_requirement_with_zero_topics(self):
        """A definitions clause has no compliance topic. Empty is correct and
        must not be papered over with an invented assignment."""
        out = self.classify(reply([], []))
        self.assertTrue(out['ok'])
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.req.topics, [])

    def test_no_hard_cap_at_one_in_the_schema(self):
        self.classify(reply([topic(t, conf=0.9) for t in
                             ('retention', 'security', 'governance',
                              'third_party', 'enforcement')]))
        self.assertEqual(len(self.rows()), 5)


# ═══════════════════════════════════════════════════════════════════════════
# D-F: deduplication
# ═══════════════════════════════════════════════════════════════════════════

class DeduplicationTests(_Base):

    def test_d_duplicate_concepts_collapse(self):
        """'retention' and 'data retention' are one topic named twice."""
        self.classify(reply([topic('retention', conf=0.7),
                             topic('data retention', conf=0.95)]))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].confidence, 0.95)

    def test_e_bare_topic_absorbed_by_its_own_subcategory(self):
        """Reuses the Phase 0 rule rather than reimplementing it."""
        self.classify(reply([topic('retention', conf=0.9),
                             topic('retention', 'secure_disposal', conf=0.85)]))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].leaf, 'retention/secure_disposal')

    def test_f_distinct_subcategories_under_one_topic_both_survive(self):
        """Different obligations, not duplication."""
        self.classify(reply([topic('retention', 'retention_periods', conf=0.9),
                             topic('retention', 'secure_disposal', conf=0.85)]))
        self.assertEqual(
            sorted(r.leaf for r in self.rows()),
            ['retention/retention_periods', 'retention/secure_disposal'])

    def test_w_no_duplicate_rows_at_database_level(self):
        self.classify(reply([topic('retention'), topic('retention'),
                             topic('storage limitation')]))
        leaves = [r.leaf for r in self.rows()]
        self.assertEqual(len(leaves), len(set(leaves)))

    def test_absorption_does_not_cross_topics(self):
        self.classify(reply([topic('retention', conf=0.9),
                             topic('security', 'access_control', conf=0.8)]))
        self.assertEqual(sorted(r.leaf for r in self.rows()),
                         ['retention', 'security/access_control'])


# ═══════════════════════════════════════════════════════════════════════════
# G-I: resolution methods
# ═══════════════════════════════════════════════════════════════════════════

class ResolutionMethodTests(_Base):

    def test_g_alias_resolution(self):
        self.classify(reply([topic('data storage period')]))
        row = self.rows()[0]
        self.assertEqual(row.topic, 'retention')
        self.assertEqual(row.resolution_method, RT.ALIAS)
        self.assertEqual(row.model_concept, 'data storage period')

    def test_exact_resolution(self):
        self.classify(reply([topic('retention')]))
        self.assertEqual(self.rows()[0].resolution_method, RT.EXACT)

    def test_h_normalized_resolution(self):
        self.classify(reply([topic('Security controls')]))
        row = self.rows()[0]
        self.assertEqual(row.topic, 'security')
        self.assertEqual(row.resolution_method, RT.NORMALIZED)

    def test_i_semantic_resolution(self):
        from apps.library.tests.test_taxonomy_resolution import make_embed_fn
        fn = make_embed_fn(('security', 'technical_measures'), best=0.9, runner=0.4)
        classify_and_store(self.req, chat=stub(reply([topic('protecting assets')])),
                           embed_fn=fn, dry_run=False)
        row = self.rows()[0]
        self.assertEqual(row.topic, 'security')
        self.assertEqual(row.resolution_method, RT.SEMANTIC)

    def test_model_concept_always_preserved(self):
        """Auditability: what the model actually said, next to what it became."""
        self.classify(reply([topic('storage limitation')]))
        row = self.rows()[0]
        self.assertEqual(row.model_concept, 'storage limitation')
        self.assertEqual(row.topic, 'retention')
        self.assertEqual(row.resolution_method, RT.ALIAS)

    def test_evidence_is_stored(self):
        self.classify(reply([topic('retention', evidence='no longer than five years')]))
        self.assertEqual(self.rows()[0].evidence, 'no longer than five years')


# ═══════════════════════════════════════════════════════════════════════════
# J-L: the three outcomes
# ═══════════════════════════════════════════════════════════════════════════

class OutcomeTests(_Base):

    def test_j_unresolved_concept_is_preserved_not_forced(self):
        self.classify(reply([], [candidate('algorithmic impact assessment')]))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].assignment, RT.SUGGESTED)
        self.assertEqual(rows[0].topic, '')
        self.assertEqual(rows[0].model_concept, 'algorithmic impact assessment')

    def test_unresolved_keeps_the_models_justification(self):
        self.classify(reply([], [candidate(
            'automated decision registers', reason='a register of ADM systems',
            why='governance is about processing records, not ADM systems')]))
        row = self.rows()[0]
        self.assertIn('register', row.reason)
        self.assertIn('governance', row.why_insufficient)

    def test_k_low_confidence_is_not_an_official_topic(self):
        self.classify(reply([topic('retention', conf=0.12)]))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].assignment, RT.UNCLASSIFIED)
        self.assertEqual(rows[0].topic, '')
        self.assertEqual(self.req.topics, [])

    def test_low_confidence_concept_is_kept_as_evidence_about_the_model(self):
        self.classify(reply([topic('retention', conf=0.12)]))
        self.assertEqual(self.rows()[0].model_concept, 'retention')

    def test_l_no_fit_response_records_nothing(self):
        """A bare decline is an answer, not a concept. It must not become a row
        called 'none' that later reads as a proposed topic."""
        self.classify(reply([topic('none', conf=0.9)]))
        self.assertEqual(self.rows(), [])

    def test_unresolved_and_unclassified_are_different_states(self):
        self.classify(reply([topic('retention', conf=0.1)],
                            [candidate('quantum key rotation policy')]))
        kinds = {r.assignment for r in self.rows()}
        self.assertEqual(kinds, {RT.UNCLASSIFIED, RT.SUGGESTED})

    def test_matched_and_unresolved_coexist(self):
        self.classify(reply([topic('retention', conf=0.9)],
                            [candidate('algorithmic impact assessment')]))
        self.assertEqual(
            {r.assignment for r in self.rows()}, {RT.MATCHED, RT.SUGGESTED})

    def test_candidate_that_is_really_an_existing_topic_is_not_a_suggestion(self):
        """Taxonomy-spam guard: a model proposing "storage limitation" as NEW
        has simply not recognised the taxonomy's own "retention"."""
        self.classify(reply([], [candidate('storage limitation')]))
        row = self.rows()[0]
        self.assertEqual(row.assignment, RT.MATCHED)
        self.assertEqual(row.topic, 'retention')

    def test_several_distinct_unresolved_concepts_all_survive(self):
        """The partial unique constraint must not cap a requirement at one
        open concept — they all share a blank topic."""
        self.classify(reply([], [candidate('algorithmic impact assessment'),
                                 candidate('quantum key rotation')]))
        self.assertEqual(
            RT.objects.filter(requirement=self.req,
                              assignment=RT.SUGGESTED).count(), 2)


# ═══════════════════════════════════════════════════════════════════════════
# N: the mirror
# ═══════════════════════════════════════════════════════════════════════════

class MirrorTests(_Base):

    def test_n_mirror_holds_official_topics_in_rank_order(self):
        self.classify(reply([topic('security', conf=0.84),
                             topic('retention', conf=0.91)]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['retention', 'security'])

    def test_mirror_excludes_unresolved_concepts(self):
        """Putting them here would recreate the uncontrolled free-text
        vocabulary this phase replaced, in the very field that used to hold it."""
        self.classify(reply([topic('retention')],
                            [candidate('data minimisation variant')]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['retention'])

    def test_mirror_excludes_unclassified(self):
        self.classify(reply([topic('retention', conf=0.1)]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, [])

    def test_mirror_deduplicates_topic_tags(self):
        self.classify(reply([topic('retention', 'retention_periods', conf=0.9),
                             topic('retention', 'secure_disposal', conf=0.8)]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['retention'])

    def test_mirror_is_rebuilt_from_rows_not_from_model_output(self):
        self.req.topics = ['garbage', 'free text']
        self.req.save(update_fields=['topics'])
        self.classify(reply([topic('retention')]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['retention'])

    def test_sync_mirror_touches_only_the_topics_field(self):
        before = (self.req.text, self.req.source_quote, self.req.key)
        RT.objects.create(requirement=self.req, topic='security',
                          assignment=RT.MATCHED, rank=0)
        sync_topics_mirror(self.req)
        self.req.refresh_from_db()
        self.assertEqual((self.req.text, self.req.source_quote, self.req.key), before)
        self.assertEqual(self.req.topics, ['security'])


# ═══════════════════════════════════════════════════════════════════════════
# O, P: idempotency and human assignments
# ═══════════════════════════════════════════════════════════════════════════

class IdempotencyTests(_Base):

    def test_o_reclassification_is_idempotent(self):
        payload = reply([topic('retention', conf=0.9), topic('security', conf=0.8)])
        self.classify(payload)
        first = [(r.topic, r.subcategory, r.rank) for r in self.rows()]
        self.classify(payload)
        self.assertEqual([(r.topic, r.subcategory, r.rank) for r in self.rows()],
                         first)
        self.assertEqual(len(self.rows()), 2)

    def test_reclassification_replaces_rather_than_accumulates(self):
        self.classify(reply([topic('retention')]))
        self.classify(reply([topic('security')]))
        self.assertEqual([r.topic for r in self.rows()], ['security'])

    def test_p_human_assignment_survives_reclassification(self):
        RT.objects.create(requirement=self.req, topic='governance',
                          assignment=RT.HUMAN, resolution_method=RT.HUMAN_M,
                          confidence=1.0, rank=0)
        self.classify(reply([topic('retention')]))
        topics = {r.topic for r in self.rows()}
        self.assertIn('governance', topics)
        self.assertIn('retention', topics)
        self.assertTrue(
            RT.objects.filter(requirement=self.req, assignment=RT.HUMAN).exists())

    def test_human_assignment_is_never_overwritten_by_the_model(self):
        RT.objects.create(requirement=self.req, topic='retention',
                          subcategory='', assignment=RT.HUMAN,
                          resolution_method=RT.HUMAN_M, confidence=1.0,
                          evidence='reviewer decision', rank=0)
        out = self.classify(reply([topic('retention', conf=0.4)]))
        row = RT.objects.get(requirement=self.req, topic='retention')
        self.assertEqual(row.assignment, RT.HUMAN)
        self.assertEqual(row.evidence, 'reviewer decision')
        self.assertEqual(out['skipped_human'], 1)

    def test_human_assignment_ranks_above_a_confident_model_topic(self):
        RT.objects.create(requirement=self.req, topic='governance',
                          assignment=RT.HUMAN, resolution_method=RT.HUMAN_M,
                          confidence=0.0, rank=5)
        self.classify(reply([topic('retention', conf=0.99)]))
        self.assertEqual(self.rows()[0].topic, 'governance')

    def test_human_assignment_appears_in_the_mirror(self):
        RT.objects.create(requirement=self.req, topic='governance',
                          assignment=RT.HUMAN, resolution_method=RT.HUMAN_M,
                          rank=0)
        self.classify(reply([topic('retention')]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.topics, ['governance', 'retention'])

    def test_failed_classification_leaves_existing_rows_alone(self):
        """A technical failure is not evidence the previous assignments were
        wrong, so it must not clear them."""
        self.classify(reply([topic('retention')]))
        out = classify_and_store(self.req, chat=stub(None, fail=True), dry_run=False)
        self.assertFalse(out['ok'])
        self.assertEqual([r.topic for r in self.rows()], ['retention'])


# ═══════════════════════════════════════════════════════════════════════════
# Q, R, V: metadata and ordering
# ═══════════════════════════════════════════════════════════════════════════

class MetadataTests(_Base):

    def test_q_taxonomy_version_is_stored(self):
        self.classify(reply([topic('retention')]))
        self.assertEqual(self.rows()[0].taxonomy_version,
                         taxonomy.TAXONOMY_VERSION)

    def test_q_taxonomy_version_stored_on_unresolved_rows_too(self):
        self.classify(reply([], [candidate('algorithmic impact assessment')]))
        self.assertEqual(self.rows()[0].taxonomy_version,
                         taxonomy.TAXONOMY_VERSION)

    def test_r_model_version_is_stored(self):
        self.classify(reply([topic('retention')]))
        self.assertEqual(self.rows()[0].model_version, CLASSIFIER_VERSION)

    def test_assignment_is_not_stale_at_the_current_version(self):
        self.classify(reply([topic('retention')]))
        self.assertFalse(self.rows()[0].is_stale)

    def test_assignment_from_an_unknown_version_reads_as_stale(self):
        self.classify(reply([topic('retention')]))
        row = self.rows()[0]
        row.taxonomy_version = 'v0-ancient'
        row.save(update_fields=['taxonomy_version'])
        self.assertTrue(row.is_stale)

    def test_v_rank_orders_by_confidence(self):
        self.classify(reply([topic('security', conf=0.5),
                             topic('retention', conf=0.95),
                             topic('governance', conf=0.7)]))
        self.assertEqual([(r.rank, r.topic) for r in self.rows()],
                         [(0, 'retention'), (1, 'governance'), (2, 'security')])

    def test_rank_is_contiguous_from_zero(self):
        self.classify(reply([topic('retention', conf=0.9),
                             topic('security', conf=0.8)],
                            [candidate('novel concept')]))
        self.assertEqual([r.rank for r in self.rows()], [0, 1, 2])

    def test_rank_zero_does_not_mean_only_correct_topic(self):
        self.classify(reply([topic('retention', conf=0.91),
                             topic('security', conf=0.90)]))
        rows = self.rows()
        self.assertEqual(rows[0].rank, 0)
        self.assertEqual(rows[1].assignment, RT.MATCHED)
        self.assertTrue(rows[1].is_official)

    def test_matched_outranks_suggested(self):
        self.classify(reply([topic('retention', conf=0.4)],
                            [candidate('novel concept', conf=0.99)]))
        self.assertEqual(self.rows()[0].assignment, RT.MATCHED)

    def test_rank_is_deterministic_on_tied_confidence(self):
        payload = reply([topic('security', conf=0.8), topic('retention', conf=0.8)])
        self.classify(payload)
        first = [r.topic for r in self.rows()]
        self.classify(payload)
        self.assertEqual([r.topic for r in self.rows()], first)


# ═══════════════════════════════════════════════════════════════════════════
# S, T: safety
# ═══════════════════════════════════════════════════════════════════════════

class SafetyTests(_Base):

    def test_s_requirement_survives_a_model_failure(self):
        out = classify_and_store(self.req, chat=stub(None, fail=True), dry_run=False)
        self.assertFalse(out['ok'])
        self.req.refresh_from_db()
        self.assertTrue(Requirement.objects.filter(pk=self.req.pk).exists())
        self.assertIn('retain personal data', self.req.text)

    def test_s_requirement_survives_an_unparseable_reply(self):
        for bad in ({}, None, [], 'not a dict', {'nonsense': 1}):
            with self.subTest(bad=bad):
                out = classify_and_store(self.req, chat=stub(bad), dry_run=False)
                self.assertFalse(out['ok'])
                self.assertTrue(Requirement.objects.filter(pk=self.req.pk).exists())

    def test_s_extraction_fields_are_never_written(self):
        before = (self.req.text, self.req.title, self.req.source_quote,
                  self.req.key, self.req.article_ref, self.req.source_chunk_id,
                  self.req.extraction_source, self.req.extraction_model)
        self.classify(reply([topic('retention'), topic('security')]))
        self.req.refresh_from_db()
        self.assertEqual(
            (self.req.text, self.req.title, self.req.source_quote,
             self.req.key, self.req.article_ref, self.req.source_chunk_id,
             self.req.extraction_source, self.req.extraction_model), before)

    def test_t_model_cannot_create_an_official_topic(self):
        before = {t: sorted(b['subcategories']) for t, b in taxonomy.TAXONOMY.items()}
        self.classify(reply([topic('a wholly invented topic', conf=0.99)],
                            [candidate('another invented topic', conf=0.99)]))
        after = {t: sorted(b['subcategories']) for t, b in taxonomy.TAXONOMY.items()}
        self.assertEqual(before, after)
        self.assertEqual(taxonomy.TAXONOMY_VERSION, taxonomy.fingerprint_of(taxonomy.TAXONOMY))
        self.assertEqual(len(taxonomy.TAXONOMY), 12)

    def test_t_invented_topic_never_becomes_an_official_assignment(self):
        self.classify(reply([topic('a wholly invented topic', conf=0.99)]))
        for row in self.rows():
            self.assertNotEqual(row.assignment, RT.MATCHED)
            self.assertEqual(row.topic, '')

    def test_t_every_matched_row_is_a_valid_taxonomy_leaf(self):
        self.classify(reply([topic('retention'), topic('storage limitation'),
                             topic('Security controls'), topic('dsar')]))
        for row in self.rows():
            if row.assignment == RT.MATCHED:
                self.assertTrue(
                    taxonomy.is_valid(row.topic, row.subcategory or None),
                    f'{row.leaf} is not an official leaf')

    def test_classification_does_not_touch_chunk_tags(self):
        """Phase 2 must leave the chunk pipeline entirely alone."""
        from retrieval import bm25_store
        called = []
        original = bm25_store.upsert_chunk_tags
        bm25_store.upsert_chunk_tags = lambda rows: called.append(rows)
        try:
            self.classify(reply([topic('retention'), topic('security')]))
        finally:
            bm25_store.upsert_chunk_tags = original
        self.assertEqual(called, [])


# ═══════════════════════════════════════════════════════════════════════════
# Classifier layer (no database)
# ═══════════════════════════════════════════════════════════════════════════

class _FakeReq:
    text = 'A controller shall retain data and protect it.'
    source_quote = 'shall retain and protect'
    article_ref = 'Article (12)'
    regulation = None


class ClassifierTests(SimpleTestCase):

    def test_empty_topics_is_a_success_not_a_failure(self):
        """A model that cleanly answered "nothing applies" must not look like a
        broken Ollama."""
        res = classify_requirement(_FakeReq(), chat=stub(reply([], [])))
        self.assertTrue(res.ok)
        self.assertEqual(res.concepts, [])

    def test_technical_failure_is_flagged(self):
        res = classify_requirement(_FakeReq(), chat=stub({}))
        self.assertFalse(res.ok)
        self.assertIn('empty', res.error)

    def test_missing_confidence_is_not_invented(self):
        """Defaulting a confidence the model never gave would fabricate the
        number the audit trail exists to record."""
        res = classify_requirement(_FakeReq(), chat=stub(
            {'topics': [{'concept': 'retention', 'evidence': 'x'}]}))
        self.assertTrue(res.ok)
        self.assertEqual(res.matched, [])
        self.assertEqual(len(res.unclassified), 1)

    def test_requirement_with_no_text_fails_cleanly(self):
        class Empty:
            text = ''
        res = classify_requirement(Empty(), chat=stub(reply([topic('retention')])))
        self.assertFalse(res.ok)

    def test_max_topics_bounds_model_output(self):
        res = classify_requirement(
            _FakeReq(),
            chat=stub(reply([topic(t, conf=0.9) for t in list(taxonomy.TAXONOMY)])),
            max_topics=3)
        self.assertLessEqual(len(res.matched), 3)

    def test_malformed_entries_are_skipped_not_fatal(self):
        res = classify_requirement(_FakeReq(), chat=stub(
            {'topics': [None, 'string', {'concept': ''},
                        topic('retention')]}))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.matched), 1)

    def test_dict_instead_of_list_is_tolerated(self):
        res = classify_requirement(_FakeReq(),
                                   chat=stub({'topics': topic('retention')}))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.matched), 1)


class PlanAssignmentsTests(SimpleTestCase):
    """plan_assignments is pure, so dry-run and write compute the same thing."""

    def test_plan_is_identical_for_the_same_input(self):
        res = classify_requirement(
            _FakeReq(), chat=stub(reply([topic('retention'), topic('security')])))
        self.assertEqual(plan_assignments(res), plan_assignments(res))

    def test_plan_ranks_contiguously(self):
        res = classify_requirement(_FakeReq(), chat=stub(
            reply([topic('retention', conf=0.9), topic('security', conf=0.8)],
                  [candidate('novel')])))
        self.assertEqual([r['rank'] for r in plan_assignments(res)], [0, 1, 2])


# ═══════════════════════════════════════════════════════════════════════════
# Service + command
# ═══════════════════════════════════════════════════════════════════════════

class RegulationPassTests(TestCase):

    def setUp(self):
        self.reg = Document.objects.create(
            name='Pass Reg', doc_type=Document.REGULATION, jurisdiction='bahrain')
        for i in range(3):
            Requirement.objects.create(
                regulation=self.reg, key=f'k{i}', text=f'Rule {i} about data.',
                article_ref=f'Article ({i})', source_chunk_id=f'n{i}',
                source_quote=f'quote {i}')

    def test_dry_run_writes_nothing(self):
        rep = classify_requirements_for_regulation(
            self.reg, chat=stub(reply([topic('retention'), topic('security')])),
            dry_run=True)
        self.assertEqual(rep['classified'], 3)
        self.assertEqual(rep['multi_topic'], 3)
        self.assertEqual(RT.objects.count(), 0)

    def test_apply_writes(self):
        rep = classify_requirements_for_regulation(
            self.reg, chat=stub(reply([topic('retention'), topic('security')])),
            dry_run=False)
        self.assertEqual(RT.objects.count(), 6)
        self.assertEqual(rep['matched'], 6)

    def test_statistics_shape(self):
        rep = classify_requirements_for_regulation(
            self.reg, chat=stub(reply([topic('retention')],
                                      [candidate('novel concept')])),
            dry_run=True)
        self.assertEqual(rep['one_topic'], 3)
        self.assertEqual(rep['suggested'], 3)
        self.assertEqual(rep['by_topic']['retention'], 3)
        self.assertEqual(rep['unresolved_concepts']['novel concept'], 3)

    def test_one_failure_does_not_stop_the_pass(self):
        calls = {'n': 0}

        def flaky(_prompt, _model=None):
            calls['n'] += 1
            if calls['n'] == 2:
                raise RuntimeError('boom')
            return reply([topic('retention')])

        rep = classify_requirements_for_regulation(
            self.reg, chat=flaky, dry_run=False)
        self.assertEqual(rep['classified'], 2)
        self.assertEqual(rep['failed'], 1)
        self.assertEqual(Requirement.objects.filter(regulation=self.reg).count(), 3)


class CommandTests(TestCase):

    def setUp(self):
        self.reg = Document.objects.create(
            name='Cmd Reg', doc_type=Document.REGULATION, jurisdiction='bahrain')
        Requirement.objects.create(
            regulation=self.reg, key='c1', text='A rule about retention.',
            article_ref='Article (1)', source_chunk_id='n1', source_quote='q')

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('classify_requirements', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_dry_run_is_the_default(self):
        import apps.library.topics as mod
        original = mod.classify_requirement
        mod.classify_requirement = lambda req, **kw: original(
            req, chat=stub(reply([topic('retention')])),
            **{k: v for k, v in kw.items() if k != 'chat'})
        self.addCleanup(setattr, mod, 'classify_requirement', original)
        out = self._run(str(self.reg.pk))
        self.assertIn('DRY RUN', out)
        self.assertIn('CORPUS SUMMARY', out)
        self.assertEqual(RT.objects.count(), 0)

    def test_missing_document_reports_cleanly(self):
        self.assertIn('No document with id 999999', self._run('999999'))

    def test_no_argument_reports_cleanly(self):
        self.assertIn('Give a document id or --all', self._run())
