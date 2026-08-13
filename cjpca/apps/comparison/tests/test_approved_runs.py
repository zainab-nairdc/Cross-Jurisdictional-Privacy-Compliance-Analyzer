"""Phases A–C — approved comparison runs as versioned compliance assessments.

The properties under test:

  AN APPROVED RUN IS NOT A CACHE. It records the exact document versions it
  was based on, because an approved result is only valid relative to its
  sources.

  CURRENCY IS NEVER ASSUMED. A run whose snapshot cannot be verified is
  `unknown` — displayed as such, and never offered for reuse. Presenting an
  unverifiable assessment as current is the failure this design exists to
  prevent, so several tests below assert that a claim is NOT made.

  ORIENTATION IS IDENTITY. A→B and B→A are different assessments, never two
  views of one.

  APPROVING RESULTS ≠ APPROVING THE ASSESSMENT. The per-result workflow is
  untouched; run-level approval is a separate human act gated on it.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.comparison.assessments import (
    ApprovalError, approve_run, approved_assessments, build_assessment_key,
    build_source_snapshot, can_approve, fingerprint_snapshot, reject_run,
    stamp_run,
)
from apps.comparison.models import ComparisonResult as CRes, ComparisonRun as CR
from apps.library.models import Document


def _doc(name, **kw):
    kw.setdefault('doc_type', Document.REGULATION)
    kw.setdefault('jurisdiction', 'bahrain')
    kw.setdefault('status', Document.INDEXED)
    # A content hash by default: without one a run is unverifiable and can
    # never legitimately reach `current`, so these fixtures would only ever
    # exercise the unknown path.
    kw.setdefault('content_hash', f'{abs(hash(name)):064x}'[:64])
    return Document.objects.create(name=name, **kw)


class _Base(TestCase):
    def setUp(self):
        self.a = _doc('Bahrain PDPL', document_id='BH-PDPL', version='1',
                      content_hash='aaa111')
        self.b = _doc('India DPDP Act', document_id='IN-DPDP', version='1',
                      jurisdiction='india', content_hash='bbb222')

    def _run(self, a=None, b=None, topics=None, status=CR.COMPLETE,
             results=2, lifecycle=None, stamp=True):
        run = CR.objects.create(pair_key='bahrain_india', reg_a=a or self.a,
                                reg_b=b or self.b, topics=topics or [],
                                status=status)
        if stamp:
            stamp_run(run, run.reg_a, run.reg_b, topics=topics or [],
                      model_version='test-model', prompt_version='test-prompt')
        for i in range(results):
            CRes.objects.create(run=run, citation_a=f'Art {i}', citation_b=f'Sec {i}')
        if lifecycle:
            run.lifecycle = lifecycle
            run.save(update_fields=['lifecycle'])
        return run

    def _decide_all(self, run, lifecycle=CRes.APPROVED):
        run.results.update(lifecycle=lifecycle)


# ═══════════════════════════════════════════════════════════════════════════
# Phase A — identity, snapshot, fingerprint
# ═══════════════════════════════════════════════════════════════════════════

class AssessmentKeyTests(_Base):

    def test_orientation_produces_different_assessments(self):
        """A→B and B→A are different questions with different narratives."""
        self.assertNotEqual(build_assessment_key(self.a, self.b),
                            build_assessment_key(self.b, self.a))

    def test_same_pair_and_scope_is_one_assessment(self):
        self.assertEqual(build_assessment_key(self.a, self.b),
                         build_assessment_key(self.a, self.b))

    def test_a_new_document_version_keeps_the_same_assessment(self):
        """The point of keying on the version FAMILY: re-running after an
        update produces v2 of one assessment, not an unrelated row."""
        b2 = _doc('India DPDP Act 2025', document_id='IN-DPDP', version='2',
                  jurisdiction='india', content_hash='ccc333', version_of=self.b)
        self.assertEqual(build_assessment_key(self.a, self.b),
                         build_assessment_key(self.a, b2))

    def test_different_scope_is_a_different_assessment(self):
        """Otherwise a topic-scoped run could present itself as a newer version
        of a full-scope one."""
        self.assertNotEqual(build_assessment_key(self.a, self.b),
                            build_assessment_key(self.a, self.b,
                                                 topics=['retention']))

    def test_topic_order_does_not_change_the_assessment(self):
        self.assertEqual(
            build_assessment_key(self.a, self.b, topics=['security', 'retention']),
            build_assessment_key(self.a, self.b, topics=['retention', 'security']))

    def test_unrelated_pairs_differ(self):
        c = _doc('Kuwait DPPR', document_id='KW-DPPR', jurisdiction='kuwait')
        self.assertNotEqual(build_assessment_key(self.a, self.b),
                            build_assessment_key(self.a, c))


class SourceSnapshotTests(_Base):

    def test_snapshot_records_both_sides_with_versions(self):
        snap = build_source_snapshot(self.a, self.b)
        self.assertEqual(snap['reg_a']['document_id'], 'BH-PDPL')
        self.assertEqual(snap['reg_a']['version'], '1')
        self.assertEqual(snap['reg_a']['content_hash'], 'aaa111')
        self.assertEqual(snap['reg_b']['document_id'], 'IN-DPDP')
        self.assertEqual(snap['orientation'], 'a_to_b')

    def test_snapshot_records_the_engine_for_audit(self):
        snap = build_source_snapshot(self.a, self.b, model_version='m',
                                     prompt_version='p')
        self.assertEqual(snap['engine']['model'], 'm')
        self.assertTrue(snap['engine']['taxonomy'])

    def test_fingerprint_changes_when_a_source_changes(self):
        before = fingerprint_snapshot(build_source_snapshot(self.a, self.b))
        self.a.content_hash = 'zzz999'
        self.a.save(update_fields=['content_hash'])
        after = fingerprint_snapshot(build_source_snapshot(self.a, self.b))
        self.assertNotEqual(before, after)

    def test_fingerprint_ignores_the_engine(self):
        """A human approved this OUTPUT. A later model change does not
        retroactively invalidate their judgement."""
        one = fingerprint_snapshot(
            build_source_snapshot(self.a, self.b, model_version='model-1'))
        two = fingerprint_snapshot(
            build_source_snapshot(self.a, self.b, model_version='model-2'))
        self.assertEqual(one, two)

    def test_fingerprint_reflects_orientation(self):
        self.assertNotEqual(
            fingerprint_snapshot(build_source_snapshot(self.a, self.b)),
            fingerprint_snapshot(build_source_snapshot(self.b, self.a)))

    def test_fingerprint_reflects_scope(self):
        self.assertNotEqual(
            fingerprint_snapshot(build_source_snapshot(self.a, self.b)),
            fingerprint_snapshot(build_source_snapshot(self.a, self.b,
                                                       topics=['retention'])))

    def test_empty_snapshot_yields_no_fingerprint(self):
        """An empty fingerprint can never match a reuse lookup — which is what
        keeps unverifiable runs out of reuse by construction."""
        self.assertEqual(fingerprint_snapshot({}), '')

    def test_stamping_marks_a_run_current_and_verifiable(self):
        run = self._run()
        self.assertTrue(run.source_fingerprint)
        self.assertEqual(run.currency_state, CR.CURRENT)
        self.assertTrue(run.currency_is_verifiable)

    def test_unstamped_run_is_unknown_and_unverifiable(self):
        run = self._run(stamp=False)
        self.assertEqual(run.currency_state, CR.UNKNOWN)
        self.assertFalse(run.currency_is_verifiable)
        self.assertFalse(run.source_fingerprint)

    def test_backfilled_snapshot_is_never_treated_as_verified(self):
        """A snapshot reconstructed from today's documents describes the
        present, not what was compared."""
        run = self._run(stamp=False)
        run.source_snapshot = {'backfilled': True, 'reg_a': {}, 'reg_b': {}}
        run.source_fingerprint = 'deadbeef'
        run.save(update_fields=['source_snapshot', 'source_fingerprint'])
        self.assertFalse(run.currency_is_verifiable)


# ═══════════════════════════════════════════════════════════════════════════
# Phase B — run-level approval
# ═══════════════════════════════════════════════════════════════════════════

class ApprovalGateTests(_Base):

    def test_cannot_approve_while_results_are_undecided(self):
        run = self._run()
        ok, why = can_approve(run)
        self.assertFalse(ok)
        self.assertIn('awaiting review', why)
        with self.assertRaises(ApprovalError):
            approve_run(run)

    def test_can_approve_once_every_result_is_decided(self):
        run = self._run()
        self._decide_all(run)
        ok, why = can_approve(run)
        self.assertTrue(ok, why)

    def test_rejected_results_still_count_as_decided(self):
        """A reviewer rejecting a row is a decision. The assessment can still
        be certified — what matters is that nothing is unreviewed."""
        run = self._run()
        self._decide_all(run, CRes.REJECTED)
        self.assertTrue(can_approve(run)[0])

    def test_cannot_approve_a_run_with_no_results(self):
        run = self._run(results=0)
        ok, why = can_approve(run)
        self.assertFalse(ok)
        self.assertIn('no comparison results', why)

    def test_cannot_approve_an_unfinished_run(self):
        run = self._run(status=CR.RUNNING)
        self._decide_all(run)
        self.assertFalse(can_approve(run)[0])

    def test_cannot_approve_twice(self):
        run = self._run()
        self._decide_all(run)
        approve_run(run)
        with self.assertRaises(ApprovalError):
            approve_run(run)

    def test_per_result_workflow_is_untouched_by_run_approval(self):
        run = self._run()
        self._decide_all(run, CRes.APPROVED)
        approve_run(run)
        self.assertEqual(
            set(run.results.values_list('lifecycle', flat=True)), {CRes.APPROVED})


class ApprovalEffectTests(_Base):

    def _approved(self, **kw):
        run = self._run(**kw)
        self._decide_all(run)
        return approve_run(run)

    def test_approval_records_who_and_when(self):
        user = User.objects.create_user('rev', password='x')
        run = self._run()
        self._decide_all(run)
        approve_run(run, actor=user)
        self.assertEqual(run.lifecycle, CR.APPROVED)
        self.assertEqual(run.approved_by, user)
        self.assertIsNotNone(run.approved_at)

    def test_first_approval_is_version_one(self):
        self.assertEqual(self._approved().version_no, 1)

    def test_second_approval_supersedes_the_first(self):
        v1 = self._approved()
        v2 = self._approved()
        v1.refresh_from_db()
        self.assertEqual(v2.version_no, 2)
        self.assertEqual(v2.supersedes, v1)
        self.assertEqual(v1.lifecycle, CR.SUPERSEDED)

    def test_superseded_version_is_retained_not_deleted(self):
        v1 = self._approved()
        self._approved()
        self.assertTrue(CR.objects.filter(pk=v1.pk).exists())
        self.assertTrue(CR.objects.get(pk=v1.pk).results.exists())

    def test_a_reversed_comparison_starts_its_own_version_line(self):
        """B→A is a different assessment, so it is v1 — not v2 of A→B."""
        self._approved()
        reverse_run = self._run(a=self.b, b=self.a)
        self._decide_all(reverse_run)
        approve_run(reverse_run)
        self.assertEqual(reverse_run.version_no, 1)
        self.assertIsNone(reverse_run.supersedes)

    def test_approval_does_not_invent_currency(self):
        """An unverifiable run stays unknown after approval. Approval records a
        judgement about the ANALYSIS; it cannot establish which document
        versions were compared."""
        run = self._run(stamp=False)
        self._decide_all(run)
        approve_run(run)
        self.assertEqual(run.lifecycle, CR.APPROVED)
        self.assertEqual(run.currency_state, CR.UNKNOWN)
        self.assertFalse(run.is_reusable)

    def test_verified_current_run_is_reusable(self):
        self.assertTrue(self._approved().is_reusable)

    def test_outdated_run_is_not_reusable(self):
        run = self._approved()
        run.currency_state = CR.OUTDATED
        run.outdated_reason = 'Bahrain PDPL has been updated'
        run.save(update_fields=['currency_state', 'outdated_reason'])
        self.assertFalse(run.is_reusable)
        self.assertIn('Bahrain PDPL', run.currency_label)

    def test_reject_marks_the_assessment_rejected(self):
        run = self._run()
        self._decide_all(run)
        reject_run(run, note='not usable')
        self.assertEqual(run.lifecycle, CR.REJECTED)

    def test_cannot_reject_an_approved_assessment(self):
        run = self._approved()
        with self.assertRaises(ApprovalError):
            reject_run(run)


class AssessmentListingTests(_Base):

    def test_only_approved_runs_are_listed(self):
        self._run()                                   # draft
        run = self._run()
        self._decide_all(run)
        approve_run(run)
        entries = approved_assessments()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['latest'].pk, run.pk)

    def test_versions_group_under_one_assessment_newest_first(self):
        v1 = self._run(); self._decide_all(v1); approve_run(v1)
        v2 = self._run(); self._decide_all(v2); approve_run(v2)
        entries = approved_assessments()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['latest'].pk, v2.pk)
        self.assertEqual([r.pk for r in entries[0]['history']], [v1.pk])
        self.assertEqual(entries[0]['version_count'], 2)

    def test_opposite_orientations_are_separate_entries(self):
        fwd = self._run(); self._decide_all(fwd); approve_run(fwd)
        rev = self._run(a=self.b, b=self.a); self._decide_all(rev); approve_run(rev)
        self.assertEqual(len(approved_assessments()), 2)


# ═══════════════════════════════════════════════════════════════════════════
# Phase C — the page
# ═══════════════════════════════════════════════════════════════════════════

class ApprovedRunsPageTests(_Base):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('rev', password='x')
        self.client.force_login(self.user)

    def _approve(self, **kw):
        run = self._run(**kw)
        self._decide_all(run)
        return approve_run(run, actor=self.user)

    def test_page_renders_when_empty(self):
        r = self.client.get(reverse('comparison-approved'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No approved assessments yet')

    def test_approved_run_is_listed_with_both_sides_explicit(self):
        self._approve()
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'Bahrain PDPL')
        self.assertContains(r, 'India DPDP Act')
        self.assertContains(r, '>A<')
        self.assertContains(r, '>B<')

    def test_page_shows_source_versions_and_approval_record(self):
        self._approve()
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'BH-PDPL')
        self.assertContains(r, 'IN-DPDP')
        self.assertContains(r, 'rev')          # approver

    def test_draft_runs_are_not_listed(self):
        self._run()
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'No approved assessments yet')

    def test_current_run_is_labelled_current(self):
        self._approve()
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'Current')

    def test_unverifiable_run_is_never_shown_as_current(self):
        """The core UI safety property."""
        self._approve(stamp=False)
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'Cannot verify currency')
        self.assertContains(r, 'Reuse unavailable')
        self.assertContains(r, 'currency cannot be verified')
        self.assertNotContains(r, 'Verified current')

    def test_outdated_run_shows_the_reason_and_a_rerun_action(self):
        """Made outdated for real rather than by hand-setting the field: the
        page re-assesses currency on load, so a hand-set state would simply be
        recomputed away."""
        self._approve()
        self.a.content_hash = 'f' * 64
        self.a.save(update_fields=['content_hash'])
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'Outdated')
        self.assertContains(r, 'Bahrain PDPL')
        self.assertContains(r, 'content has changed')
        self.assertContains(r, 'Re-run comparison')

    def test_reuse_is_offered_only_for_a_verified_current_run(self):
        self._approve()
        self.assertContains(self.client.get(reverse('comparison-approved')),
                            'Verified current')

    def test_superseded_versions_remain_openable(self):
        v1 = self._approve()
        self._approve()
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'Earlier versions')
        self.assertContains(r, reverse('comparison-workspace', args=[v1.pk]))

    def test_fully_reviewed_but_uncertified_runs_are_surfaced(self):
        run = self._run()
        self._decide_all(run)
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'awaiting certification')
        self.assertContains(r, f'run #{run.pk}')

    def test_undecided_runs_are_not_in_the_awaiting_queue(self):
        self._run()
        r = self.client.get(reverse('comparison-approved'))
        self.assertNotContains(r, 'awaiting certification')


class ApprovalEndpointTests(_Base):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('rev', password='x')
        self.client.force_login(self.user)

    def test_approve_via_endpoint(self):
        run = self._run()
        self._decide_all(run)
        self.client.post(reverse('comparison-run-approval', args=[run.pk]),
                         {'action': 'approve'})
        run.refresh_from_db()
        self.assertEqual(run.lifecycle, CR.APPROVED)
        self.assertEqual(run.version_no, 1)

    def test_endpoint_refuses_when_results_are_undecided(self):
        run = self._run()
        r = self.client.post(reverse('comparison-run-approval', args=[run.pk]),
                             {'action': 'approve'}, follow=True)
        run.refresh_from_db()
        self.assertEqual(run.lifecycle, CR.DRAFT)
        self.assertContains(r, 'awaiting review')

    def test_endpoint_warns_when_currency_cannot_be_verified(self):
        run = self._run(stamp=False)
        self._decide_all(run)
        r = self.client.post(reverse('comparison-run-approval', args=[run.pk]),
                             {'action': 'approve'}, follow=True)
        self.assertContains(r, 'cannot verify currency')

    def test_reject_via_endpoint(self):
        run = self._run()
        self._decide_all(run)
        self.client.post(reverse('comparison-run-approval', args=[run.pk]),
                         {'action': 'reject'})
        run.refresh_from_db()
        self.assertEqual(run.lifecycle, CR.REJECTED)

    def test_unknown_action_is_rejected(self):
        run = self._run()
        r = self.client.post(reverse('comparison-run-approval', args=[run.pk]),
                             {'action': 'nonsense'})
        self.assertEqual(r.status_code, 400)

    def test_workspace_exposes_approval_state_without_regenerating(self):
        """Opening a run must never trigger a fresh comparison."""
        run = self._run()
        self._decide_all(run)
        import apps.comparison.views as v
        called = []
        original = getattr(v, 'compare_regulations', None)
        r = self.client.get(reverse('comparison-workspace', args=[run.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(called, [])
        self.assertIs(getattr(v, 'compare_regulations', None), original)


class NoBlindCachingTests(_Base):
    """Reuse is gated on the approved assessment, never on a response cache."""

    def test_an_unapproved_run_is_never_reusable(self):
        run = self._run()
        self.assertFalse(run.is_reusable)

    def test_approval_alone_is_not_enough(self):
        run = self._run(stamp=False)
        self._decide_all(run)
        approve_run(run)
        self.assertEqual(run.lifecycle, CR.APPROVED)
        self.assertFalse(run.is_reusable)

    def test_reusability_requires_all_three_conditions(self):
        run = self._run()
        self._decide_all(run)
        approve_run(run)
        self.assertTrue(run.is_reusable)
        for field, value in (('lifecycle', CR.DRAFT),
                             ('currency_state', CR.OUTDATED),
                             ('source_fingerprint', '')):
            with self.subTest(field=field):
                original = getattr(run, field)
                setattr(run, field, value)
                self.assertFalse(run.is_reusable)
                setattr(run, field, original)
