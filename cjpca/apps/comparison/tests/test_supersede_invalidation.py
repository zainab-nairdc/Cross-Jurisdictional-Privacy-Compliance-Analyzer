"""Phase D4 — push invalidation when a source document is superseded.

D3 is the authoritative definition of currency. D4 only decides WHEN to
re-check, never WHAT current means: `invalidate_runs_for_document()` selects
the affected runs and hands each to `apply_currency()`. These tests exist to
prove that delegation holds — in particular that the push path and a later
pull-path re-check always agree, which they cannot do if the logic is ever
duplicated into `supersede_with()`.

The other property under test is precision: superseding one document must
touch the runs that reference it and nothing else.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.comparison.assessments import (
    apply_currency, approve_run, assess_currency, invalidate_runs_for_document,
    stamp_run,
)
from apps.comparison.models import ComparisonResult as CRes, ComparisonRun as CR
from apps.feedback.models import FeedbackSignal, GoldExemplar
from apps.library.models import Document


def _doc(name, *, content_hash=None, **kw):
    kw.setdefault('doc_type', Document.REGULATION)
    kw.setdefault('jurisdiction', 'bahrain')
    kw.setdefault('status', Document.INDEXED)
    if content_hash is None:
        content_hash = f'{abs(hash(name)):064x}'[:64]
    return Document.objects.create(name=name, content_hash=content_hash, **kw)


class _Base(TestCase):
    def setUp(self):
        self.a = _doc('Bahrain PDPL', document_id='BH-PDPL', version='1')
        self.b = _doc('India DPDP Act', document_id='IN-DPDP', version='1',
                      jurisdiction='india')
        self.c = _doc('Kuwait DPPR', document_id='KW-DPPR', version='1',
                      jurisdiction='kuwait')

    def _run(self, a=None, b=None, stamp=True, approve=False, results=2):
        run = CR.objects.create(pair_key='p', reg_a=a or self.a,
                                reg_b=b or self.b, status=CR.COMPLETE)
        if stamp:
            stamp_run(run, run.reg_a, run.reg_b, model_version='m',
                      prompt_version='p')
        for i in range(results):
            CRes.objects.create(run=run, citation_a=f'Art {i}')
        if approve:
            run.results.update(lifecycle=CRes.APPROVED)
            approve_run(run)
        return run

    def _supersede(self, old, name='Successor', actor=None):
        new = _doc(name, document_id=old.document_id, version='2',
                   jurisdiction=old.jurisdiction)
        old.supersede_with(new, actor=actor)
        return new


# ═══════════════════════════════════════════════════════════════════════════
# The push path marks dependents
# ═══════════════════════════════════════════════════════════════════════════

class PushInvalidationTests(_Base):

    def test_superseding_source_a_marks_the_run_outdated(self):
        run = self._run(approve=True)
        self.assertEqual(run.currency_state, CR.CURRENT)
        self._supersede(self.a)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)
        self.assertIn('Bahrain PDPL', run.outdated_reason)
        self.assertIn('superseded', run.outdated_reason)

    def test_superseding_source_b_marks_the_run_outdated(self):
        run = self._run(approve=True)
        self._supersede(self.b)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)
        self.assertIn('India DPDP', run.outdated_reason)

    def test_the_reason_names_the_side_that_actually_changed(self):
        run = self._run(approve=True)
        self._supersede(self.b)
        run.refresh_from_db()
        self.assertIn('India DPDP', run.outdated_reason)
        self.assertNotIn('Bahrain PDPL', run.outdated_reason)

    def test_both_orientations_are_invalidated(self):
        """The same document is A in one assessment and B in another."""
        fwd = self._run(a=self.a, b=self.b, approve=True)
        rev = self._run(a=self.b, b=self.a, approve=True)
        self._supersede(self.a)
        fwd.refresh_from_db(); rev.refresh_from_db()
        self.assertEqual(fwd.currency_state, CR.OUTDATED)
        self.assertEqual(rev.currency_state, CR.OUTDATED)
        self.assertIn('Bahrain PDPL', fwd.outdated_reason)
        self.assertIn('Bahrain PDPL', rev.outdated_reason)

    def test_currency_checked_at_is_stamped(self):
        run = self._run(approve=True)
        run.currency_checked_at = None
        run.save(update_fields=['currency_checked_at'])
        self._supersede(self.a)
        run.refresh_from_db()
        self.assertIsNotNone(run.currency_checked_at)

    def test_draft_runs_are_invalidated_too(self):
        """So a run approved later already carries the right currency, rather
        than being certified against a source that has since been replaced."""
        run = self._run(approve=False)
        self._supersede(self.a)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)


# ═══════════════════════════════════════════════════════════════════════════
# Precision — nothing else is touched
# ═══════════════════════════════════════════════════════════════════════════

class PrecisionTests(_Base):

    def test_unrelated_runs_are_untouched(self):
        related   = self._run(a=self.a, b=self.b, approve=True)
        unrelated = self._run(a=self.b, b=self.c, approve=True)
        before = (unrelated.currency_state, unrelated.currency_checked_at,
                  unrelated.outdated_reason)
        self._supersede(self.a)
        related.refresh_from_db(); unrelated.refresh_from_db()
        self.assertEqual(related.currency_state, CR.OUTDATED)
        self.assertEqual(
            (unrelated.currency_state, unrelated.currency_checked_at,
             unrelated.outdated_reason), before)

    def test_a_run_on_different_documents_stays_current(self):
        other = self._run(a=self.b, b=self.c, approve=True)
        self._supersede(self.a)
        other.refresh_from_db()
        self.assertEqual(other.currency_state, CR.CURRENT)
        self.assertTrue(other.is_reusable)

    def test_the_successor_document_is_not_marked_outdated(self):
        new = self._supersede(self.a)
        run = self._run(a=new, b=self.b, approve=True)
        self.assertEqual(run.currency_state, CR.CURRENT)

    def test_invalidating_a_document_with_no_runs_is_harmless(self):
        counts = invalidate_runs_for_document(self.c)
        self.assertEqual(counts.get('errors', 0), 0)

    def test_invalidating_none_is_harmless(self):
        self.assertEqual(invalidate_runs_for_document(None).get('errors', 0), 0)


# ═══════════════════════════════════════════════════════════════════════════
# D3 remains authoritative
# ═══════════════════════════════════════════════════════════════════════════

class D3AgreementTests(_Base):

    def test_push_and_pull_reach_the_same_verdict(self):
        """If D4 ever duplicated currency logic, these would diverge."""
        run = self._run(approve=True)
        self._supersede(self.a)
        run.refresh_from_db()
        pushed = (run.currency_state, run.outdated_reason)
        fresh = CR.objects.select_related('reg_a', 'reg_b').get(pk=run.pk)
        verdict = assess_currency(fresh)
        self.assertEqual(verdict.state, pushed[0])
        self.assertEqual(verdict.reason[:300], pushed[1])

    def test_a_later_recheck_does_not_change_the_state(self):
        run = self._run(approve=True)
        self._supersede(self.a)
        run.refresh_from_db()
        before = run.currency_state
        fresh = CR.objects.select_related('reg_a', 'reg_b').get(pk=run.pk)
        apply_currency(fresh)
        fresh.refresh_from_db()
        self.assertEqual(fresh.currency_state, before)

    def test_an_unverifiable_run_stays_unknown_not_outdated(self):
        """`unknown` already blocks reuse. Forcing it to `outdated` here would
        override the assessment and fork the definition of currency."""
        run = self._run(stamp=False, approve=True)
        self.assertEqual(run.currency_state, CR.UNKNOWN)
        self._supersede(self.a)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.UNKNOWN)

    def test_an_unverifiable_run_never_becomes_current(self):
        run = self._run(stamp=False, approve=True)
        self._supersede(self.a)
        run.refresh_from_db()
        self.assertNotEqual(run.currency_state, CR.CURRENT)
        self.assertFalse(run.is_reusable)

    def test_supersession_is_detected_even_without_content_hashes(self):
        """A stamped run whose source cannot be content-hashed is `unknown` —
        there is no way to prove the bytes unchanged. But the snapshot records
        the `superseded` flag independently of hashing, so a later supersession
        IS positive evidence of change and correctly yields `outdated`.

        Stronger than the hash path and unaffected by the corpus's patchy hash
        coverage: supersession works on every document."""
        unhashed = _doc('Unhashed', document_id='NH', content_hash='')
        run = self._run(a=unhashed, approve=True)
        self.assertEqual(run.currency_state, CR.UNKNOWN)
        self._supersede(unhashed)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)
        self.assertIn('superseded', run.outdated_reason)
        self.assertFalse(run.is_reusable)

    def test_an_unhashed_untouched_source_still_reads_unknown(self):
        """The contrast: without a supersession there is still no evidence, so
        the run stays unknown rather than drifting to current."""
        unhashed = _doc('Unhashed', document_id='NH2', content_hash='')
        run = self._run(a=unhashed, approve=True)
        self._supersede(self.b, name='India Successor')
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)   # B superseded
        other = self._run(a=_doc('Unhashed2', document_id='NH3', content_hash=''),
                          b=self.c, approve=True)
        invalidate_runs_for_document(self.a)
        other.refresh_from_db()
        self.assertEqual(other.currency_state, CR.UNKNOWN)


# ═══════════════════════════════════════════════════════════════════════════
# Idempotency
# ═══════════════════════════════════════════════════════════════════════════

class IdempotencyTests(_Base):

    def test_repeated_supersession_is_safe(self):
        run = self._run(approve=True)
        new = self._supersede(self.a)
        run.refresh_from_db()
        first = (run.currency_state, run.outdated_reason)
        for _ in range(2):
            self.a.supersede_with(new)
        run.refresh_from_db()
        self.assertEqual((run.currency_state, run.outdated_reason), first)

    def test_repeated_invalidation_is_stable(self):
        run = self._run(approve=True)
        self._supersede(self.a)
        run.refresh_from_db()
        first = (run.currency_state, run.outdated_reason)
        for _ in range(3):
            invalidate_runs_for_document(self.a)
        run.refresh_from_db()
        self.assertEqual((run.currency_state, run.outdated_reason), first)

    def test_the_reason_is_not_degraded_by_reinvalidation(self):
        """Re-running must not replace a specific reason with a vaguer one."""
        run = self._run(approve=True)
        self._supersede(self.a)
        run.refresh_from_db()
        specific = run.outdated_reason
        self.assertIn('Bahrain PDPL', specific)
        invalidate_runs_for_document(self.a)
        run.refresh_from_db()
        self.assertEqual(run.outdated_reason, specific)

    def test_a_second_changed_source_is_added_to_the_reason(self):
        run = self._run(approve=True)
        self._supersede(self.a)
        self._supersede(self.b, name='India Successor')
        run.refresh_from_db()
        self.assertIn('Bahrain PDPL', run.outdated_reason)
        self.assertIn('India DPDP', run.outdated_reason)


# ═══════════════════════════════════════════════════════════════════════════
# Nothing else may move
# ═══════════════════════════════════════════════════════════════════════════

class NonInterferenceTests(_Base):

    def test_run_lifecycle_is_unchanged(self):
        run = self._run(approve=True)
        before = (run.lifecycle, run.approved_at, run.approved_by_id,
                  run.version_no)
        self._supersede(self.a)
        run.refresh_from_db()
        self.assertEqual((run.lifecycle, run.approved_at, run.approved_by_id,
                          run.version_no), before)
        self.assertEqual(run.lifecycle, CR.APPROVED)

    def test_result_lifecycles_are_unchanged(self):
        run = self._run(approve=True, results=3)
        before = sorted(run.results.values_list('lifecycle', flat=True))
        self._supersede(self.a)
        self.assertEqual(sorted(run.results.values_list('lifecycle', flat=True)),
                         before)

    def test_results_themselves_are_unchanged(self):
        run = self._run(approve=True, results=2)
        before = sorted(run.results.values_list('citation_a', 'rationale',
                                                'relationship'))
        self._supersede(self.a)
        self.assertEqual(sorted(run.results.values_list('citation_a', 'rationale',
                                                        'relationship')), before)

    def test_no_feedback_rows_are_created(self):
        self._run(approve=True)
        self._supersede(self.a)
        self.assertEqual(FeedbackSignal.objects.count(), 0)
        self.assertEqual(GoldExemplar.objects.count(), 0)

    def test_is_reusable_becomes_false_for_the_outdated_run(self):
        run = self._run(approve=True)
        self.assertTrue(run.is_reusable)
        self._supersede(self.a)
        run.refresh_from_db()
        self.assertFalse(run.is_reusable)

    def test_supersede_still_returns_the_affected_approved_results(self):
        """The existing return contract the supersede view depends on."""
        run = self._run(approve=True, results=2)
        run.results.update(lifecycle=CRes.APPROVED)
        new = _doc('Successor', document_id='BH-PDPL', version='2')
        affected = self.a.supersede_with(new)
        self.assertIsNotNone(affected)
        self.assertEqual(affected.count(), 2)

    def test_supersession_itself_still_applies(self):
        self._run(approve=True)
        new = self._supersede(self.a)
        self.a.refresh_from_db(); new.refresh_from_db()
        self.assertTrue(self.a.superseded)
        self.assertFalse(new.superseded)
        self.assertEqual(new.version_of_id, self.a.pk)

    def test_a_comparison_side_failure_does_not_break_supersession(self):
        """Invalidation is best-effort and last, so supersession cannot be
        left half-applied by a comparison-side problem."""
        import apps.comparison.assessments as mod
        original = mod.invalidate_runs_for_document
        mod.invalidate_runs_for_document = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('boom'))
        self.addCleanup(setattr, mod, 'invalidate_runs_for_document', original)
        new = _doc('Successor', document_id='BH-PDPL', version='2')
        self.a.supersede_with(new)
        self.a.refresh_from_db()
        self.assertTrue(self.a.superseded)


class SupersedeViewTests(_Base):
    """The UI path that reaches supersede_with()."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('admin', password='x')
        self.client.force_login(self.user)

    def test_supersede_endpoint_invalidates_dependent_runs(self):
        from django.urls import reverse
        run = self._run(approve=True)
        new = _doc('Successor', document_id='BH-PDPL', version='2')
        r = self.client.post(reverse('library-supersede', args=[self.a.pk]),
                             {'new_pk': new.pk})
        self.assertEqual(r.status_code, 200)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)
