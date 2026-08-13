"""Regression tests for the RAG feedback loop's SCOPING and BOUNDING guarantees.

These pin the four properties the feedback layer must hold for a regulatory
compliance system:

  1. contextual scoping — feedback only applies to the topic it was recorded under
  2. bounded influence  — repeated approvals cannot buy unlimited ranking power
  3. version safety     — feedback from a retired taxonomy/model is inert
  4. deletion safety    — retained ("keep") feedback cannot revive on re-ingest

They use stub nodes rather than the live vector store so they are deterministic
and runnable in CI; the end-to-end proof against the real corpus lives in the
`feedback_rerank_eval` command and the scratchpad validation harnesses.
"""

from django.test import TestCase

from apps.feedback.models import FeedbackSignal, GoldExemplar
from apps.feedback.services import (
    RETIRED_KEY, chunk_feedback_scores, feedback_rerank, record_feedback,
    _node_chunk_id, _versions,
)


# ── stub retrieval nodes ─────────────────────────────────────────────────────
class _Node:
    def __init__(self, node_id):
        self.metadata = {'node_id': node_id}


class _Scored:
    """Mimics llama-index NodeWithScore closely enough for _node_chunk_id/score."""
    def __init__(self, node_id, score):
        self.node = _Node(node_id)
        self.score = score


def make_nodes():
    """Descending scores, so baseline rank == list order."""
    return [_Scored(f'chunk{i}', 1.0 - i * 0.1) for i in range(1, 6)]


def order(nodes):
    return [_node_chunk_id(n) for n in nodes]


def rank_of(nodes, cid):
    for i, n in enumerate(nodes, 1):
        if _node_chunk_id(n) == cid:
            return i
    return None


class ColdStartTests(TestCase):
    """Property: zero feedback must be an EXACT no-op."""

    def test_cold_start_is_identity(self):
        nodes = make_nodes()
        out = feedback_rerank(list(nodes))
        self.assertEqual(order(out), order(nodes))
        # not merely equal ordering — the same objects, untouched
        for a, b in zip(nodes, out):
            self.assertIs(a, b)

    def test_cold_start_scores_empty(self):
        self.assertEqual(chunk_feedback_scores(), {})
        self.assertEqual(chunk_feedback_scores(topic='lawful_basis'), {})


class TopicScopingTests(TestCase):
    """Priority 1: an approval for one topic must not re-rank other topics."""

    def setUp(self):
        # chunk4 sits at baseline rank 4; approved under 'cross_border' ONLY.
        record_feedback(kind='approve', source_id=1, topic='cross_border',
                        before={'chunk_id_a': 'chunk4'})

    def test_same_topic_feedback_boosts(self):
        nodes = make_nodes()
        self.assertEqual(rank_of(nodes, 'chunk4'), 4)
        out = feedback_rerank(list(nodes), topic='cross_border')
        # Improvement, not necessarily rank 1: the clamped boost is +0.5 on a
        # 0..1 normalised base, so chunk4 (norm 0.25 -> 0.75) passes chunk3 but
        # cannot overtake chunk1 (norm 1.0). That ceiling is the Priority-2 fix.
        self.assertLess(rank_of(out, 'chunk4'), 4,
                        'approval recorded under this topic must promote the chunk')

    def test_unrelated_topic_feedback_does_not_boost(self):
        nodes = make_nodes()
        out = feedback_rerank(list(nodes), topic='data_subject_rights')
        self.assertEqual(order(out), order(nodes),
                         'feedback from another topic must not change this ranking')
        self.assertEqual(rank_of(out, 'chunk4'), 4)

    def test_topic_scoped_scores_exclude_other_topics(self):
        self.assertEqual(chunk_feedback_scores(topic='cross_border'), {'chunk4': 1})
        self.assertEqual(chunk_feedback_scores(topic='data_subject_rights'), {})

    def test_blank_topic_signal_excluded_from_scoped_retrieval(self):
        """Relevance can't be established for an untagged signal, so a scoped
        retrieval must not assume it applies."""
        record_feedback(kind='approve', source_id=2, topic='', before={'chunk_id_a': 'chunk5'})
        self.assertNotIn('chunk5', chunk_feedback_scores(topic='cross_border'))
        self.assertIn('chunk5', chunk_feedback_scores())      # still visible unscoped

    def test_unscoped_call_preserves_global_behaviour(self):
        """topic=None means the caller is not scoped — previous behaviour stands:
        the signal applies regardless of the topic it was recorded under."""
        nodes = make_nodes()
        out = feedback_rerank(list(nodes))
        self.assertLess(rank_of(out, 'chunk4'), 4)
        self.assertEqual(chunk_feedback_scores(), {'chunk4': 1})


class BoundedBoostTests(TestCase):
    """Priority 2: influence must reach a ceiling, not grow with approval count."""

    def _net_for(self, n_approvals):
        FeedbackSignal.objects.all().delete()
        for i in range(n_approvals):
            record_feedback(kind='approve', source_id=100 + i, topic='t',
                            before={'chunk_id_a': 'chunk5'})
        return chunk_feedback_scores(topic='t').get('chunk5', 0)

    def test_raw_net_still_accumulates_for_audit(self):
        self.assertEqual(self._net_for(3), 3)

    def test_boost_reaches_a_ceiling(self):
        """0, 1, 2, 3, 5, 50 approvals: rank must plateau immediately after 1."""
        ranks = {}
        for n in (0, 1, 2, 3, 5, 50):
            self._net_for(n)
            ranks[n] = rank_of(feedback_rerank(make_nodes(), topic='t'), 'chunk5')
        self.assertEqual(ranks[0], 5, 'no feedback -> unchanged')
        self.assertEqual(ranks[1], ranks[2], 'ceiling reached after one approval')
        self.assertEqual(ranks[2], ranks[3])
        self.assertEqual(ranks[3], ranks[5])
        self.assertEqual(ranks[5], ranks[50], '50 approvals must not beat 1')

    def test_bounded_boost_cannot_exceed_alpha(self):
        """chunk5 is worst-ranked; even with 50 approvals the clamped boost (0.5)
        must not lift it past chunks more than 0.5 of the base range above it."""
        self._net_for(50)
        out = feedback_rerank(make_nodes(), topic='t')
        # base range is normalised 0..1; chunk5 norm=0.0 -> 0.0+0.5 = 0.5.
        # chunk1 norm=1.0 and chunk2 norm=0.75 both stay ahead.
        self.assertGreater(rank_of(out, 'chunk5'), 2,
                           'clamped boost must not pin a chunk at the top')

    def test_unbounded_regression_guard(self):
        """Pre-fix behaviour was boost = 0.5 * net (3 approvals => +1.5, top rank).
        This asserts we no longer do that."""
        self._net_for(3)
        out = feedback_rerank(make_nodes(), topic='t')
        self.assertNotEqual(rank_of(out, 'chunk5'), 1,
                            'unbounded boost has regressed')


class RejectionTests(TestCase):
    def test_rejection_demotes(self):
        record_feedback(kind='reject', source_id=1, topic='t',
                        before={'chunk_id_a': 'chunk1'})
        nodes = make_nodes()
        self.assertEqual(rank_of(nodes, 'chunk1'), 1)
        out = feedback_rerank(list(nodes), topic='t')
        self.assertGreater(rank_of(out, 'chunk1'), 1)

    def test_rejection_is_also_clamped(self):
        for i in range(10):
            record_feedback(kind='reject', source_id=200 + i, topic='t',
                            before={'chunk_id_a': 'chunk1'})
        one = feedback_rerank(make_nodes(), topic='t')
        FeedbackSignal.objects.all().delete()
        record_feedback(kind='reject', source_id=1, topic='t',
                        before={'chunk_id_a': 'chunk1'})
        ten = feedback_rerank(make_nodes(), topic='t')
        self.assertEqual(rank_of(one, 'chunk1'), rank_of(ten, 'chunk1'))

    def test_modify_has_no_retrieval_effect(self):
        """Documented known limitation — pinned so a change is deliberate."""
        record_feedback(kind='modify', source_id=1, topic='t',
                        before={'chunk_id_a': 'chunk4'})
        self.assertEqual(chunk_feedback_scores(topic='t'), {})
        self.assertEqual(order(feedback_rerank(make_nodes(), topic='t')),
                         order(make_nodes()))


class VersionScopingTests(TestCase):
    """Priority 3: stale feedback is inert for retrieval but kept for audit."""

    def setUp(self):
        self.sig = record_feedback(kind='approve', source_id=1, topic='t',
                                   before={'chunk_id_a': 'chunk4'})

    def test_current_version_feedback_is_used(self):
        tax, model = _versions()
        self.assertEqual(self.sig.taxonomy_version, tax)
        self.assertEqual(self.sig.model_version, model)
        self.assertEqual(chunk_feedback_scores(topic='t'), {'chunk4': 1})

    def test_obsolete_taxonomy_version_ignored(self):
        FeedbackSignal.objects.filter(pk=self.sig.pk).update(taxonomy_version='v0-OBSOLETE')
        self.assertEqual(chunk_feedback_scores(topic='t'), {})
        self.assertEqual(order(feedback_rerank(make_nodes(), topic='t')),
                         order(make_nodes()))

    def test_obsolete_model_version_ignored(self):
        FeedbackSignal.objects.filter(pk=self.sig.pk).update(model_version='retired-model:0.1')
        self.assertEqual(chunk_feedback_scores(topic='t'), {})

    def test_stale_feedback_retained_for_audit(self):
        FeedbackSignal.objects.filter(pk=self.sig.pk).update(taxonomy_version='v0-OBSOLETE')
        self.assertEqual(FeedbackSignal.objects.filter(pk=self.sig.pk).count(), 1,
                         'stale feedback must be ignored, never deleted')
        # and it is still fully readable
        s = FeedbackSignal.objects.get(pk=self.sig.pk)
        self.assertEqual(s.before['chunk_id_a'], 'chunk4')

    def test_version_scope_can_be_bypassed_for_audit_queries(self):
        FeedbackSignal.objects.filter(pk=self.sig.pk).update(taxonomy_version='v0-OBSOLETE')
        self.assertEqual(chunk_feedback_scores(topic='t', version_scope=False), {'chunk4': 1})


class TopicKeyAlignmentTests(TestCase):
    """The topic a signal is filed under MUST equal the topic retrieval scoped by,
    or topic-scoping would silently discard every signal."""

    def _result(self, run_topics, principle_ids):
        from apps.library.models import Document
        from apps.comparison.models import ComparisonRun, ComparisonResult
        a = Document.objects.create(name='A', doc_type='regulation')
        b = Document.objects.create(name='B', doc_type='regulation')
        run = ComparisonRun.objects.create(pair_key='t', reg_a=a, reg_b=b,
                                           topics=run_topics, status='complete')
        return ComparisonResult.objects.create(
            run=run, citation_a='A', citation_b='B', relationship='equivalent',
            confidence=0.9, principle_ids=principle_ids,
            chunk_id_a='chunk4', chunk_id_b='')

    def test_run_topic_wins_over_fuzzy_principle_ids(self):
        """The run was retrieved with topic='cross_border'; the fuzzy text probe
        guessed 'lawful_basis'. The signal must be filed under the retrieval topic."""
        from apps.feedback.services import capture_comparison_transition
        res = self._result(run_topics=['cross_border'], principle_ids=['lawful_basis'])
        sig = capture_comparison_transition(res, 'approved', actor=None)
        self.assertEqual(sig.topic, 'cross_border')
        self.assertEqual(chunk_feedback_scores(topic='cross_border'), {'chunk4': 1})
        self.assertEqual(chunk_feedback_scores(topic='lawful_basis'), {})

    def test_falls_back_to_principle_ids_for_full_scope_runs(self):
        from apps.feedback.services import capture_comparison_transition
        res = self._result(run_topics=[], principle_ids=['lawful_basis'])
        sig = capture_comparison_transition(res, 'approved', actor=None)
        self.assertEqual(sig.topic, 'lawful_basis')

    def test_end_to_end_topic_round_trip(self):
        """Approve under a topic, then confirm a retrieval scoped to that SAME
        topic sees it and a differently-scoped one does not."""
        from apps.feedback.services import capture_comparison_transition
        res = self._result(run_topics=['security'], principle_ids=[])
        capture_comparison_transition(res, 'approved', actor=None)
        boosted = feedback_rerank(make_nodes(), topic='security')
        self.assertLess(rank_of(boosted, 'chunk4'), 4)
        untouched = feedback_rerank(make_nodes(), topic='retention')
        self.assertEqual(rank_of(untouched, 'chunk4'), 4)


class DeletionAndReingestionTests(TestCase):
    """Priority 4: 'keep' retains for audit but must be inert, including after the
    same document title is re-ingested (chunk ids are a deterministic hash)."""

    def setUp(self):
        from apps.library.models import Document
        from apps.comparison.models import ComparisonRun, ComparisonResult
        self.doc = Document.objects.create(name='TestReg', doc_type='regulation')
        self.other = Document.objects.create(name='OtherReg', doc_type='regulation')
        run = ComparisonRun.objects.create(pair_key='t', reg_a=self.doc, reg_b=self.other,
                                           topics=['t'], status='complete')
        self.result = ComparisonResult.objects.create(
            run=run, citation_a='A', citation_b='B', relationship='equivalent',
            confidence=0.9, principle_ids=['t'],
            chunk_id_a='chunk4', chunk_id_b='')
        from apps.feedback.services import capture_comparison_transition
        capture_comparison_transition(self.result, 'approved', actor=None)

    def test_footprint_reports_counts(self):
        from apps.feedback.services import document_learning_footprint
        self.assertEqual(document_learning_footprint(self.doc),
                         {'signals': 1, 'gold': 1})

    def test_keep_retains_for_audit(self):
        from apps.feedback.services import purge_document_learning
        purge_document_learning(self.doc, mode='keep')
        s = FeedbackSignal.objects.get(source_id=self.result.pk)
        self.assertIn('[source document deleted: TestReg]', s.note)
        self.assertEqual(s.before['chunk_id_a'], 'chunk4',
                         'original evidence must stay readable for audit')
        self.assertEqual(GoldExemplar.objects.filter(source_id=self.result.pk).count(), 1)

    def test_keep_makes_feedback_inert_for_retrieval(self):
        from apps.feedback.services import purge_document_learning
        self.assertEqual(chunk_feedback_scores(topic='t'), {'chunk4': 1})
        purge_document_learning(self.doc, mode='keep')
        self.assertEqual(chunk_feedback_scores(topic='t'), {},
                         'retained feedback must not influence retrieval')
        self.assertEqual(order(feedback_rerank(make_nodes(), topic='t')),
                         order(make_nodes()))

    def test_keep_deactivates_gold(self):
        from apps.feedback.services import purge_document_learning, gold_for_topic
        purge_document_learning(self.doc, mode='keep')
        g = GoldExemplar.objects.get(source_id=self.result.pk)
        self.assertFalse(g.active)
        self.assertEqual(gold_for_topic('t'), [],
                         'deactivated gold must not be reusable as few-shot')

    def test_reingestion_does_not_revive_feedback(self):
        """Same doc title re-ingested -> byte-identical chunk ids (md5 of
        doc_title::chunk_id::index). Retired feedback must stay inert."""
        from apps.comparison.models import ComparisonRun
        from apps.feedback.services import purge_document_learning
        from apps.library.models import Document
        purge_document_learning(self.doc, mode='keep')
        # ComparisonRun.reg_a/reg_b are PROTECT, so a document a comparison was
        # built on cannot be deleted while that run exists — the run has to go
        # first. This test is about feedback surviving a re-ingest, not about
        # deletion protection, so it just follows the required order.
        ComparisonRun.objects.filter(reg_a=self.doc).delete()
        self.doc.delete()
        # re-ingest: same title, so ingestion regenerates the SAME chunk ids
        Document.objects.create(name='TestReg', doc_type='regulation')
        self.assertEqual(chunk_feedback_scores(topic='t'), {},
                         'old feedback revived after re-ingesting the same title')
        self.assertEqual(order(feedback_rerank(make_nodes(), topic='t')),
                         order(make_nodes()))

    def test_purge_removes_everything(self):
        from apps.feedback.services import purge_document_learning
        out = purge_document_learning(self.doc, mode='purge')
        self.assertEqual(out['signals'], 1)
        self.assertEqual(out['gold'], 1)
        self.assertEqual(FeedbackSignal.objects.filter(source_id=self.result.pk).count(), 0)
        self.assertEqual(GoldExemplar.objects.filter(source_id=self.result.pk).count(), 0)
        self.assertEqual(chunk_feedback_scores(topic='t'), {})

    def test_retired_marker_skipped_directly(self):
        s = FeedbackSignal.objects.get(source_id=self.result.pk)
        b = s.before
        b[RETIRED_KEY] = True
        s.before = b
        s.save(update_fields=['before'])
        self.assertEqual(chunk_feedback_scores(topic='t'), {})
