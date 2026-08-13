"""Phase E — offer an approved assessment instead of re-running the comparison.

The guarantee under test:

    An approved assessment is OFFERED, never applied. A person always chooses,
    "re-run anyway" is always available, and accepting reuse performs ZERO LLM
    calls and creates ZERO new rows.

Eligibility is `is_reusable` (approved AND current AND currency-verifiable) and
nothing else — this phase adds no second gate and relaxes no existing one. On
top of it sit two exact-match questions: is this the same comparison, and the
same scope.

Scope matching is EXACT on purpose. A full-scope assessment is not treated as
covering a narrower request, because proving that would mean inferring coverage
from per-result evidence that is incomplete in this corpus.
"""

from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.comparison.assessments import (
    SCOPE_MODE_DIFFERS, SCOPE_TOPICS_DIFFER, SCOPE_UNVERIFIABLE,
    approve_run, find_reusable_run, stamp_run, verify_scope_coverage,
)
from apps.comparison.models import ComparisonResult as CRes, ComparisonRun as CR
from apps.feedback.models import FeedbackSignal, GoldExemplar
from apps.history.audit import Actions
from apps.history.models import AuditLog
from apps.library.models import Document


def _doc(name, **kw):
    kw.setdefault('doc_type', Document.REGULATION)
    kw.setdefault('jurisdiction', 'bahrain')
    kw.setdefault('status', Document.INDEXED)
    kw.setdefault('content_hash', f'{abs(hash(name)):064x}'[:64])
    return Document.objects.create(name=name, **kw)


class _Base(TestCase):
    def setUp(self):
        self.a = _doc('Bahrain PDPL', document_id='BH-PDPL')
        self.b = _doc('India DPDP Act', document_id='IN-DPDP', jurisdiction='india')
        self.c = _doc('Kuwait DPPR', document_id='KW-DPPR', jurisdiction='kuwait')

    def _run(self, a=None, b=None, topics=None, scope_mode='',
             approve=True, stamp=True, results=2):
        run = CR.objects.create(pair_key='p', reg_a=a or self.a, reg_b=b or self.b,
                                topics=topics or [], status=CR.COMPLETE)
        if stamp:
            stamp_run(run, run.reg_a, run.reg_b, topics=topics or [],
                      scope_mode=scope_mode, model_version='m')
        for i in range(results):
            CRes.objects.create(run=run, citation_a=f'Art {i}')
        if approve:
            run.results.update(lifecycle=CRes.APPROVED)
            approve_run(run)
        return run


# ═══════════════════════════════════════════════════════════════════════════
# E1 — eligibility
# ═══════════════════════════════════════════════════════════════════════════

class EligibilityTests(_Base):

    def test_approved_current_verifiable_run_is_found(self):
        run = self._run()
        self.assertTrue(run.is_reusable)
        self.assertEqual(find_reusable_run(self.a, self.b), run)

    def test_unapproved_run_is_not_offered(self):
        self._run(approve=False)
        self.assertIsNone(find_reusable_run(self.a, self.b))

    def test_outdated_run_is_not_offered(self):
        run = self._run()
        run.currency_state = CR.OUTDATED
        run.save(update_fields=['currency_state'])
        self.assertIsNone(find_reusable_run(self.a, self.b))

    def test_unknown_currency_run_is_not_offered(self):
        run = self._run()
        run.currency_state = CR.UNKNOWN
        run.save(update_fields=['currency_state'])
        self.assertIsNone(find_reusable_run(self.a, self.b))

    def test_unverifiable_run_is_not_offered(self):
        """No snapshot means currency cannot be established, so `is_reusable`
        is false however the state field happens to read."""
        run = self._run(stamp=False)
        run.currency_state = CR.CURRENT
        run.save(update_fields=['currency_state'])
        self.assertFalse(run.is_reusable)
        self.assertIsNone(find_reusable_run(self.a, self.b))

    def test_rejected_run_is_not_offered(self):
        run = self._run(approve=False)
        run.lifecycle = CR.REJECTED
        run.save(update_fields=['lifecycle'])
        self.assertIsNone(find_reusable_run(self.a, self.b))

    def test_superseded_run_is_not_offered(self):
        """Only the current approved version may be reused."""
        self._run()
        self._run()                       # supersedes the first
        found = find_reusable_run(self.a, self.b)
        self.assertEqual(found.version_no, 2)
        self.assertEqual(found.lifecycle, CR.APPROVED)

    def test_lookup_never_writes(self):
        run = self._run()
        before = (run.lifecycle, run.currency_state, run.currency_checked_at,
                  run.version_no, CR.objects.count(), CRes.objects.count())
        find_reusable_run(self.a, self.b)
        run.refresh_from_db()
        self.assertEqual((run.lifecycle, run.currency_state, run.currency_checked_at,
                          run.version_no, CR.objects.count(), CRes.objects.count()),
                         before)


class SourceMatchingTests(_Base):

    def test_same_documents_match(self):
        run = self._run(a=self.a, b=self.b)
        self.assertEqual(find_reusable_run(self.a, self.b), run)

    def test_reversed_orientation_does_not_match(self):
        """A→B and B→A are different assessments with different narratives."""
        self._run(a=self.a, b=self.b)
        self.assertIsNone(find_reusable_run(self.b, self.a))

    def test_different_source_a_does_not_match(self):
        self._run(a=self.a, b=self.b)
        self.assertIsNone(find_reusable_run(self.c, self.b))

    def test_different_source_b_does_not_match(self):
        self._run(a=self.a, b=self.b)
        self.assertIsNone(find_reusable_run(self.a, self.c))

    def test_another_version_of_the_same_law_does_not_match(self):
        """assessment_key is family-based, so two versions share it. The
        requested version must be the one actually compared."""
        run = self._run(a=self.a, b=self.b)
        newer = _doc('Bahrain PDPL 2026', document_id='BH-PDPL', version_of=self.a)
        self.assertIsNone(find_reusable_run(newer, self.b))
        self.assertEqual(find_reusable_run(self.a, self.b), run)

    def test_missing_documents_are_handled(self):
        self.assertIsNone(find_reusable_run(None, self.b))
        self.assertIsNone(find_reusable_run(self.a, None))
        self.assertIsNone(find_reusable_run(Document(), self.b))


class DeterminismTests(_Base):

    def test_newest_approved_version_wins(self):
        v1 = self._run()
        v2 = self._run()
        self.assertEqual(v2.version_no, 2)
        self.assertEqual(find_reusable_run(self.a, self.b), v2)
        v1.refresh_from_db()
        self.assertEqual(v1.lifecycle, CR.SUPERSEDED)

    def test_repeated_lookups_return_the_same_run(self):
        self._run()
        self._run()
        picks = {find_reusable_run(self.a, self.b).pk for _ in range(5)}
        self.assertEqual(len(picks), 1)


# ═══════════════════════════════════════════════════════════════════════════
# E2 — exact scope coverage
# ═══════════════════════════════════════════════════════════════════════════

class ScopeCoverageTests(_Base):

    def test_full_scope_request_matches_full_scope_run(self):
        run = self._run()
        ok, _, _ = verify_scope_coverage(run, [], 'full')
        self.assertTrue(ok)
        self.assertEqual(find_reusable_run(self.a, self.b, [], 'full'), run)

    def test_identical_topic_set_matches(self):
        run = self._run(topics=['retention', 'security'])
        ok, _, _ = verify_scope_coverage(run, ['retention', 'security'], 'topics')
        self.assertTrue(ok)

    def test_topic_order_does_not_matter(self):
        run = self._run(topics=['retention', 'security'])
        ok, _, _ = verify_scope_coverage(run, ['security', 'retention'], 'topics')
        self.assertTrue(ok)
        self.assertEqual(
            find_reusable_run(self.a, self.b, ['security', 'retention'], 'topics'),
            run)

    def test_duplicate_topics_do_not_matter(self):
        run = self._run(topics=['retention', 'security'])
        ok, _, _ = verify_scope_coverage(
            run, ['security', 'retention', 'security'], 'topics')
        self.assertTrue(ok)

    def test_different_topic_set_does_not_match(self):
        run = self._run(topics=['retention', 'security'])
        ok, code, _ = verify_scope_coverage(run, ['retention'], 'topics')
        self.assertFalse(ok)
        self.assertEqual(code, SCOPE_TOPICS_DIFFER)
        self.assertIsNone(find_reusable_run(self.a, self.b, ['retention'], 'topics'))

    def test_extra_requested_topic_does_not_match(self):
        self._run(topics=['retention'])
        self.assertIsNone(find_reusable_run(
            self.a, self.b, ['retention', 'security'], 'topics'))

    def test_full_scope_run_does_not_satisfy_a_narrower_request(self):
        """EXACT MATCHING. Proving a full run covers a topic would mean
        inferring coverage from incomplete per-result evidence."""
        run = self._run()
        ok, code, _ = verify_scope_coverage(run, ['retention'], 'topics')
        self.assertFalse(ok)
        self.assertEqual(code, SCOPE_MODE_DIFFERS)
        self.assertIsNone(find_reusable_run(self.a, self.b, ['retention'], 'topics'))

    def test_narrow_run_does_not_satisfy_a_full_request(self):
        self._run(topics=['retention'])
        self.assertIsNone(find_reusable_run(self.a, self.b, [], 'full'))

    def test_missing_scope_block_is_unverifiable(self):
        run = self._run()
        snap = dict(run.source_snapshot)
        snap.pop('scope', None)
        run.source_snapshot = snap
        run.save(update_fields=['source_snapshot'])
        ok, code, _ = verify_scope_coverage(run, [], 'full')
        self.assertFalse(ok)
        self.assertEqual(code, SCOPE_UNVERIFIABLE)

    def test_scope_is_read_from_the_snapshot_not_run_topics(self):
        """The snapshot is the immutable record of what was asked for."""
        run = self._run(topics=['retention'])
        run.topics = ['security']            # divergent, deliberately
        run.save(update_fields=['topics'])
        ok, _, _ = verify_scope_coverage(run, ['retention'], 'topics')
        self.assertTrue(ok)

    def test_coverage_check_never_writes(self):
        run = self._run(topics=['retention'])
        before = run.source_snapshot
        verify_scope_coverage(run, ['retention'], 'topics')
        run.refresh_from_db()
        self.assertEqual(run.source_snapshot, before)

    def test_partial_result_evidence_is_never_used(self):
        """principle_ids on results must not be read as coverage proof."""
        run = self._run()
        run.results.update(principle_ids=['retention'])
        self.assertIsNone(find_reusable_run(self.a, self.b, ['retention'], 'topics'))


# ═══════════════════════════════════════════════════════════════════════════
# E3 / E4 — the interstitial, the two choices, and the audit trail
# ═══════════════════════════════════════════════════════════════════════════

class _ViewBase(_Base):
    """Drives RunComparisonView with the model patched out.

    `compare_regulations_auto` is the entry point the full-scope path calls.
    Patching it lets the forced-rerun path complete without Ollama AND gives
    the zero-LLM assertions something concrete to check.
    """

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('analyst', password='x')
        self.client.force_login(self.user)
        # A report the persistence code can actually consume: no obligations,
        # and a real dict from model_dump() so report_json stays serialisable.
        report = mock.MagicMock(name='report')
        report.obligations = []
        report.model_dump.return_value = {'obligations': [], 'summary': ''}
        self.llm = mock.MagicMock(name='compare_regulations_auto',
                                  return_value=report)
        patcher = mock.patch('reasoning.workflows.compare_regulations_auto',
                             self.llm)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, **extra):
        data = {'reg_a_pk': self.a.pk, 'reg_b_pk': self.b.pk,
                'scope_mode': 'full'}
        data.update(extra)
        return self.client.post(reverse('comparison-run'), data)


class InterstitialTests(_ViewBase):

    def test_eligible_candidate_renders_the_offer(self):
        run = self._run()
        r = self._post()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'An approved, current assessment already exists')
        self.assertContains(r, f'Assessment #{run.pk}')

    def test_offer_identifies_both_sources_and_the_scope(self):
        self._run()
        r = self._post()
        self.assertContains(r, 'Bahrain PDPL')
        self.assertContains(r, 'India DPDP Act')
        self.assertContains(r, 'Full scope')

    def test_offer_presents_both_choices(self):
        self._run()
        r = self._post()
        self.assertContains(r, 'Use existing assessment')
        self.assertContains(r, 'Re-run anyway')

    def test_no_run_is_created_before_the_analyst_chooses(self):
        self._run()
        before = CR.objects.count()
        self._post()
        self.assertEqual(CR.objects.count(), before)

    def test_no_llm_call_before_the_analyst_chooses(self):
        self._run()
        self._post()
        self.llm.assert_not_called()

    def test_no_results_created_before_the_choice(self):
        self._run()
        before = CRes.objects.count()
        self._post()
        self.assertEqual(CRes.objects.count(), before)

    def test_no_candidate_falls_through_to_the_normal_path(self):
        """With nothing reusable, behaviour is exactly as before Phase E."""
        before = CR.objects.count()
        r = self._post()
        self.assertEqual(CR.objects.count(), before + 1)
        self.assertEqual(r.status_code, 302)
        self.llm.assert_called_once()

    def test_scope_mismatch_falls_through_to_the_normal_path(self):
        self._run(topics=['retention'], scope_mode='topics')
        before = CR.objects.count()
        self._post()          # full-scope request
        self.assertEqual(CR.objects.count(), before + 1)


class AcceptReuseTests(_ViewBase):

    def test_accepting_opens_the_existing_assessment(self):
        run = self._run()
        r = self._post(use_existing=str(run.pk))
        self.assertRedirects(r, reverse('comparison-workspace', args=[run.pk]),
                             fetch_redirect_response=False)

    def test_accepting_creates_no_run_and_no_results(self):
        run = self._run()
        runs, results = CR.objects.count(), CRes.objects.count()
        self._post(use_existing=str(run.pk))
        self.assertEqual(CR.objects.count(), runs)
        self.assertEqual(CRes.objects.count(), results)

    def test_accepting_performs_zero_llm_calls(self):
        """THE guarantee. Reuse must never reach the comparison workflow."""
        run = self._run()
        self._post(use_existing=str(run.pk))
        self.llm.assert_not_called()

    def test_accepting_changes_no_lifecycle_or_currency(self):
        run = self._run()
        before = (run.lifecycle, run.currency_state, run.outdated_reason,
                  run.version_no, run.approved_at)
        self._post(use_existing=str(run.pk))
        run.refresh_from_db()
        self.assertEqual((run.lifecycle, run.currency_state, run.outdated_reason,
                          run.version_no, run.approved_at), before)

    def test_accepting_changes_no_results(self):
        run = self._run(results=2)
        before = sorted(run.results.values_list('citation_a', 'lifecycle'))
        self._post(use_existing=str(run.pk))
        self.assertEqual(sorted(run.results.values_list('citation_a', 'lifecycle')),
                         before)

    def test_accepting_creates_no_feedback_rows(self):
        run = self._run()
        self._post(use_existing=str(run.pk))
        self.assertEqual(FeedbackSignal.objects.count(), 0)
        self.assertEqual(GoldExemplar.objects.count(), 0)

    def test_a_stale_use_existing_id_does_not_reuse(self):
        """A posted id that no longer answers this request must not be recorded
        as an accepted reuse — it falls through to a real run."""
        run = self._run()
        run.currency_state = CR.OUTDATED
        run.save(update_fields=['currency_state'])
        before = CR.objects.count()
        self._post(use_existing=str(run.pk))
        self.assertEqual(CR.objects.count(), before + 1)
        self.assertFalse(AuditLog.objects.filter(
            event_type=Actions.COMPARISON_REUSE_ACCEPTED).exists())

    def test_a_foreign_run_id_cannot_be_accepted(self):
        """Posting the id of an assessment that does not answer THIS request
        must not reuse it. The request is re-resolved from scratch, so the
        analyst is shown the offer for the run that genuinely matches — and
        the foreign run is never recorded as accepted."""
        legit = self._run()
        other = self._run(a=self.a, b=self.c)
        before = CR.objects.count()
        r = self._post(use_existing=str(other.pk))

        self.assertFalse(AuditLog.objects.filter(
            event_type=Actions.COMPARISON_REUSE_ACCEPTED,
            related_object_id=other.pk).exists())
        self.assertEqual(CR.objects.count(), before)      # nothing created
        self.llm.assert_not_called()
        self.assertContains(r, f'Assessment #{legit.pk}')


class ForceRerunTests(_ViewBase):

    def test_forcing_creates_a_new_run(self):
        self._run()
        before = CR.objects.count()
        r = self._post(force_rerun='1')
        self.assertEqual(CR.objects.count(), before + 1)
        self.assertEqual(r.status_code, 302)

    def test_forcing_invokes_the_normal_comparison_flow(self):
        self._run()
        self._post(force_rerun='1')
        self.llm.assert_called_once()

    def test_forcing_leaves_the_approved_run_untouched(self):
        run = self._run(results=2)
        before = (run.lifecycle, run.currency_state, run.version_no,
                  run.approved_at, run.source_fingerprint,
                  sorted(run.results.values_list('citation_a', 'lifecycle')))
        self._post(force_rerun='1')
        run.refresh_from_db()
        self.assertEqual((run.lifecycle, run.currency_state, run.version_no,
                          run.approved_at, run.source_fingerprint,
                          sorted(run.results.values_list('citation_a', 'lifecycle'))),
                         before)

    def test_forcing_creates_exactly_one_run(self):
        self._run()
        before = CR.objects.count()
        self._post(force_rerun='1')
        self.assertEqual(CR.objects.count(), before + 1)

    def test_the_new_run_starts_unapproved(self):
        self._run()
        self._post(force_rerun='1')
        newest = CR.objects.order_by('-pk').first()
        self.assertEqual(newest.lifecycle, CR.DRAFT)

    def test_forcing_creates_no_feedback_rows(self):
        self._run()
        self._post(force_rerun='1')
        self.assertEqual(FeedbackSignal.objects.count(), 0)
        self.assertEqual(GoldExemplar.objects.count(), 0)


class AuditTests(_ViewBase):

    def test_offer_is_audited(self):
        run = self._run()
        self._post()
        row = AuditLog.objects.filter(
            event_type=Actions.COMPARISON_REUSE_OFFERED).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.related_object_id, run.pk)

    def test_acceptance_is_audited(self):
        run = self._run()
        self._post(use_existing=str(run.pk))
        row = AuditLog.objects.filter(
            event_type=Actions.COMPARISON_REUSE_ACCEPTED).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.related_object_id, run.pk)

    def test_forced_rerun_is_audited(self):
        self._run()
        self._post(force_rerun='1')
        self.assertTrue(AuditLog.objects.filter(
            event_type=Actions.COMPARISON_RERUN_FORCED).exists())

    def test_no_reuse_events_when_nothing_is_reusable(self):
        self._post()
        for action in (Actions.COMPARISON_REUSE_OFFERED,
                       Actions.COMPARISON_REUSE_ACCEPTED,
                       Actions.COMPARISON_RERUN_FORCED):
            self.assertFalse(AuditLog.objects.filter(event_type=action).exists(),
                             action)

    def test_reuse_events_follow_the_existing_naming_convention(self):
        for action in (Actions.COMPARISON_REUSE_OFFERED,
                       Actions.COMPARISON_REUSE_ACCEPTED,
                       Actions.COMPARISON_RERUN_FORCED):
            self.assertTrue(action.startswith('comparison.'), action)


# ═══════════════════════════════════════════════════════════════════════════
# E5 — contextual re-run from Approved Runs
# ═══════════════════════════════════════════════════════════════════════════

class ContextualRerunTests(_ViewBase):
    """The link must carry the assessment's own sources and scope, and must
    never execute anything by itself."""

    def _link_for(self, run):
        from django.utils.html import escape
        r = self.client.get(reverse('comparison-approved'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        marker = f'reg_a_pk={run.reg_a_id}'
        self.assertIn(marker, html, 'no contextual re-run link rendered')
        start = html.index(marker)
        return escape(html[start - 60:start + 240])

    def _outdate(self, run):
        """Make the run GENUINELY outdated, which is when the re-run link shows.

        Hand-setting `currency_state` would not survive: the Approved Runs page
        re-assesses currency on load (D3), so the state has to follow from a
        real source change.
        """
        doc = run.reg_a
        doc.content_hash = 'f' * 64
        doc.save(update_fields=['content_hash'])
        return run

    def test_link_prefills_both_sources_preserving_orientation(self):
        run = self._outdate(self._run(a=self.a, b=self.b))
        link = self._link_for(run)
        self.assertIn(f'reg_a_pk={self.a.pk}', link)
        self.assertIn(f'reg_b_pk={self.b.pk}', link)

    def test_link_prefills_full_scope(self):
        run = self._outdate(self._run())
        self.assertIn('scope_mode=full', self._link_for(run))

    def test_link_prefills_topics(self):
        run = self._outdate(self._run(topics=['retention', 'security'],
                                      scope_mode='topics'))
        link = self._link_for(run)
        self.assertIn('scope_mode=topics', link)
        self.assertIn('topics=retention', link)
        self.assertIn('topics=security', link)

    def test_picker_accepts_the_prefill_without_running_anything(self):
        run = self._outdate(self._run(topics=['retention'], scope_mode='topics'))
        before = CR.objects.count()
        r = self.client.get(reverse('comparison'), {
            'reg_a_pk': run.reg_a_id, 'reg_b_pk': run.reg_b_id,
            'scope_mode': 'topics', 'topics': ['retention']})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(CR.objects.count(), before)
        self.llm.assert_not_called()

    def test_picker_marks_the_prefilled_scope_mode(self):
        r = self.client.get(reverse('comparison'), {
            'reg_a_pk': self.a.pk, 'reg_b_pk': self.b.pk,
            'scope_mode': 'topics', 'topics': ['retention']})
        self.assertContains(r, "scopeMode:'topics'")

    def test_picker_defaults_are_unchanged_without_prefill(self):
        r = self.client.get(reverse('comparison'))
        self.assertContains(r, "scopeMode:'full'")

    def test_an_invalid_scope_mode_is_ignored(self):
        r = self.client.get(reverse('comparison'), {
            'reg_a_pk': self.a.pk, 'reg_b_pk': self.b.pk,
            'scope_mode': 'nonsense'})
        self.assertContains(r, "scopeMode:'full'")

    def test_contextual_rerun_does_not_change_the_original_run(self):
        run = self._outdate(self._run(results=2))
        before = (run.lifecycle, run.currency_state, run.version_no,
                  run.approved_at, run.results.count())
        self.client.get(reverse('comparison'), {
            'reg_a_pk': run.reg_a_id, 'reg_b_pk': run.reg_b_id,
            'scope_mode': 'full'})
        run.refresh_from_db()
        self.assertEqual((run.lifecycle, run.currency_state, run.version_no,
                          run.approved_at, run.results.count()), before)
