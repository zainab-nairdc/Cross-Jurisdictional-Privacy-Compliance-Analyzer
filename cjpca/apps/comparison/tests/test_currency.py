"""Phase D — currency detection for approved comparison assessments.

The invariant every test here defends:

    CURRENT requires POSITIVE EVIDENCE that both sources still match the
    stamped state. Missing evidence is UNKNOWN, never CURRENT.

The dangerous implementation is the easy one: recompute the fingerprint,
compare, call it current. Most documents in this corpus have no content_hash,
so two empty hashes match and their fingerprints match — which would vouch for
an assessment nothing can actually stand behind. `test_empty_hash_on_both_sides`
and `test_fingerprint_match_on_empty_hashes_is_not_current` exist specifically
to fail if that shortcut ever gets taken.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.comparison.assessments import (
    SIDE_CHANGED, SIDE_UNVERIFIABLE, SIDE_VERIFIED, apply_currency,
    approve_run, assess_currency, refresh_approved_currency,
    refresh_currency_for, stamp_run,
)
from apps.comparison.models import ComparisonResult as CRes, ComparisonRun as CR
from apps.feedback.models import FeedbackSignal, GoldExemplar
from apps.library.models import Document


def _doc(name, *, content_hash='', **kw):
    kw.setdefault('doc_type', Document.REGULATION)
    kw.setdefault('jurisdiction', 'bahrain')
    kw.setdefault('status', Document.INDEXED)
    return Document.objects.create(name=name, content_hash=content_hash, **kw)


class _Base(TestCase):
    """Both sources hashed by default — the verifiable baseline."""

    def setUp(self):
        self.a = _doc('Bahrain PDPL', document_id='BH-PDPL', version='1',
                      content_hash='a' * 64)
        self.b = _doc('India DPDP Act', document_id='IN-DPDP', version='1',
                      jurisdiction='india', content_hash='b' * 64)

    def _run(self, a=None, b=None, stamp=True, results=1, approve=False):
        run = CR.objects.create(pair_key='bahrain_india', reg_a=a or self.a,
                                reg_b=b or self.b, status=CR.COMPLETE)
        if stamp:
            stamp_run(run, run.reg_a, run.reg_b, model_version='model-1',
                      prompt_version='prompt-1')
        for i in range(results):
            CRes.objects.create(run=run, citation_a=f'Art {i}')
        if approve:
            run.results.update(lifecycle=CRes.APPROVED)
            approve_run(run)
        return run


# ═══════════════════════════════════════════════════════════════════════════
# CURRENT — only on positive evidence
# ═══════════════════════════════════════════════════════════════════════════

class CurrentTests(_Base):

    def test_unchanged_verifiable_sources_are_current(self):
        v = assess_currency(self._run())
        self.assertEqual(v.state, CR.CURRENT)
        self.assertEqual(v.reason, '')
        self.assertTrue(all(s.state == SIDE_VERIFIED for s in v.sides))

    def test_current_requires_both_sides_verified(self):
        v = assess_currency(self._run())
        self.assertEqual([s.state for s in v.sides],
                         [SIDE_VERIFIED, SIDE_VERIFIED])


# ═══════════════════════════════════════════════════════════════════════════
# OUTDATED
# ═══════════════════════════════════════════════════════════════════════════

class OutdatedTests(_Base):

    def test_one_changed_source_is_outdated_and_names_it(self):
        run = self._run()
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        v = assess_currency(run)
        self.assertEqual(v.state, CR.OUTDATED)
        self.assertIn('Bahrain PDPL', v.reason)
        self.assertIn('content has changed', v.reason)
        self.assertNotIn('India DPDP', v.reason)

    def test_the_other_side_changing_is_also_detected(self):
        run = self._run()
        self.b.content_hash = 'z' * 64
        self.b.save(update_fields=['content_hash'])
        v = assess_currency(run)
        self.assertEqual(v.state, CR.OUTDATED)
        self.assertIn('India DPDP', v.reason)

    def test_both_changed_names_both_sources(self):
        run = self._run()
        self.a.content_hash = 'y' * 64
        self.b.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        self.b.save(update_fields=['content_hash'])
        v = assess_currency(run)
        self.assertEqual(v.state, CR.OUTDATED)
        self.assertIn('Bahrain PDPL', v.reason)
        self.assertIn('India DPDP', v.reason)
        self.assertEqual(len(v.changed_sides), 2)

    def test_superseded_source_is_outdated(self):
        run = self._run()
        self.a.superseded = True
        self.a.save(update_fields=['superseded'])
        v = assess_currency(run)
        self.assertEqual(v.state, CR.OUTDATED)
        self.assertIn('superseded', v.reason)

    def test_supersession_wins_over_an_unchanged_hash(self):
        """A superseded document is reported as superseded even when its bytes
        are identical — that is the more meaningful fact for a reviewer."""
        run = self._run()
        self.a.superseded = True
        self.a.save(update_fields=['superseded'])
        v = assess_currency(run)
        self.assertIn('superseded', v.reason)
        self.assertNotIn('content has changed', v.reason)

    def test_a_newer_version_makes_the_run_outdated(self):
        run = self._run()
        _doc('Bahrain PDPL 2025', document_id='BH-PDPL', content_hash='c' * 64,
             version_of=self.a)
        v = assess_currency(run)
        self.assertEqual(v.state, CR.OUTDATED)
        self.assertIn('newer version', v.reason)

    def test_a_newer_version_of_an_already_superseded_source_is_not_news(self):
        """The run was knowingly made against an old version, so the newer one
        existing is not a change since stamping."""
        self.a.superseded = True
        self.a.save(update_fields=['superseded'])
        run = self._run()
        _doc('Bahrain PDPL 2025', content_hash='c' * 64, version_of=self.a)
        self.assertEqual(assess_currency(run).state, CR.CURRENT)

    def test_replaced_document_identity_is_outdated(self):
        run = self._run()
        snap = dict(run.source_snapshot)
        snap['reg_a'] = {**snap['reg_a'], 'pk': 999999}
        run.source_snapshot = snap
        run.save(update_fields=['source_snapshot'])
        v = assess_currency(run)
        self.assertEqual(v.state, CR.OUTDATED)
        self.assertIn('replaced', v.reason)


# ═══════════════════════════════════════════════════════════════════════════
# UNKNOWN — the empty-evidence rule
# ═══════════════════════════════════════════════════════════════════════════

class UnknownTests(_Base):

    def test_empty_hash_on_side_a_is_unknown(self):
        a = _doc('Unhashed A', document_id='NO-HASH-A')
        run = self._run(a=a)
        v = assess_currency(run)
        self.assertEqual(v.state, CR.UNKNOWN)
        self.assertIn('no content hash', v.reason)

    def test_empty_hash_on_side_b_is_unknown(self):
        b = _doc('Unhashed B', document_id='NO-HASH-B', jurisdiction='india')
        v = assess_currency(self._run(b=b))
        self.assertEqual(v.state, CR.UNKNOWN)

    def test_empty_hashes_on_both_sides_are_unknown_not_current(self):
        """THE regression test. Two empty hashes are equal, and equality here
        is not evidence of anything."""
        a = _doc('Unhashed A', document_id='NH-A')
        b = _doc('Unhashed B', document_id='NH-B', jurisdiction='india')
        v = assess_currency(self._run(a=a, b=b))
        self.assertEqual(v.state, CR.UNKNOWN)
        self.assertNotEqual(v.state, CR.CURRENT)
        self.assertTrue(all(s.state == SIDE_UNVERIFIABLE for s in v.sides))

    def test_fingerprint_match_on_empty_hashes_is_not_current(self):
        """Fingerprints built from two empty hashes match. The verdict must
        still be UNKNOWN — the fingerprint may never short-circuit the walk."""
        a = _doc('Unhashed A', document_id='NH-A')
        b = _doc('Unhashed B', document_id='NH-B', jurisdiction='india')
        v = assess_currency(self._run(a=a, b=b))
        self.assertTrue(v.fingerprint_matched)
        self.assertEqual(v.state, CR.UNKNOWN)

    def test_hash_added_after_stamping_is_unknown_not_outdated(self):
        """Backfilling a hash is not a source change — nothing about the
        document moved, we simply became able to measure it."""
        a = _doc('Later hashed', document_id='LH')
        run = self._run(a=a)
        a.content_hash = 'd' * 64
        a.save(update_fields=['content_hash'])
        v = assess_currency(run)
        self.assertEqual(v.state, CR.UNKNOWN)
        self.assertNotEqual(v.state, CR.OUTDATED)

    def test_hash_removed_after_stamping_is_unknown(self):
        run = self._run()
        self.a.content_hash = ''
        self.a.save(update_fields=['content_hash'])
        self.assertEqual(assess_currency(run).state, CR.UNKNOWN)

    def test_stamping_does_not_fabricate_current_for_unhashable_sources(self):
        """stamp_run() must ASSESS, not assume. Capturing a snapshot of two
        documents that have no content hash records two empty hashes — nothing
        will ever be able to prove them unchanged, so the run is unknown from
        the moment it is stamped, and the first re-check must agree."""
        a = _doc('Unhashed A', document_id='SA')
        b = _doc('Unhashed B', document_id='SB', jurisdiction='india')
        run = self._run(a=a, b=b)
        self.assertEqual(run.currency_state, CR.UNKNOWN)
        self.assertEqual(assess_currency(run).state, CR.UNKNOWN)

    def test_stamp_time_and_check_time_agree(self):
        """Otherwise the very first re-check would silently change the state."""
        for pair in (('h1' * 32, 'h2' * 32), ('', 'h2' * 32), ('', '')):
            with self.subTest(pair=pair):
                a = _doc(f'A{pair}', document_id=f'A{pair[0][:4]}',
                         content_hash=pair[0])
                b = _doc(f'B{pair}', document_id=f'B{pair[1][:4]}',
                         jurisdiction='india', content_hash=pair[1])
                run = self._run(a=a, b=b)
                self.assertEqual(run.currency_state, assess_currency(run).state)

    def test_legacy_unstamped_run_is_unknown(self):
        v = assess_currency(self._run(stamp=False))
        self.assertEqual(v.state, CR.UNKNOWN)
        self.assertIn('predates source-version tracking', v.reason)

    def test_backfilled_snapshot_is_unknown(self):
        run = self._run(stamp=False)
        run.source_snapshot = {'backfilled': True, 'reg_a': {}, 'reg_b': {}}
        run.source_fingerprint = 'deadbeef'
        run.save(update_fields=['source_snapshot', 'source_fingerprint'])
        self.assertEqual(assess_currency(run).state, CR.UNKNOWN)

    def test_a_changed_source_outranks_an_unverifiable_one(self):
        """A proven change is more actionable than an unmeasurable side."""
        b = _doc('Unhashed B', document_id='NH-B', jurisdiction='india')
        run = self._run(b=b)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        v = assess_currency(run)
        self.assertEqual(v.state, CR.OUTDATED)


# ═══════════════════════════════════════════════════════════════════════════
# Engine changes must NOT affect source currency
# ═══════════════════════════════════════════════════════════════════════════

class EngineChangeTests(_Base):

    def test_model_change_alone_keeps_the_run_current(self):
        run = self._run()
        run.model_version = 'model-2'
        run.save(update_fields=['model_version'])
        self.assertEqual(assess_currency(run).state, CR.CURRENT)

    def test_prompt_change_alone_keeps_the_run_current(self):
        run = self._run()
        run.prompt_version = 'prompt-9'
        run.save(update_fields=['prompt_version'])
        self.assertEqual(assess_currency(run).state, CR.CURRENT)

    def test_taxonomy_change_alone_keeps_the_run_current(self):
        run = self._run()
        run.taxonomy_version = 'v9-different'
        run.save(update_fields=['taxonomy_version'])
        self.assertEqual(assess_currency(run).state, CR.CURRENT)

    def test_engine_fields_in_the_snapshot_do_not_matter(self):
        run = self._run()
        snap = dict(run.source_snapshot)
        snap['engine'] = {'model': 'totally-different', 'prompt': 'x',
                          'taxonomy': 'y'}
        run.source_snapshot = snap
        run.save(update_fields=['source_snapshot'])
        self.assertEqual(assess_currency(run).state, CR.CURRENT)

    def test_free_form_version_string_alone_is_not_a_signal(self):
        """'1.0' / '42/2020' / full RBI circular numbers — too inconsistent to
        be evidence of anything."""
        run = self._run()
        self.a.version = 'completely different string'
        self.a.save(update_fields=['version'])
        self.assertEqual(assess_currency(run).state, CR.CURRENT)


# ═══════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════

class ApplyCurrencyTests(_Base):

    def test_apply_persists_state_and_timestamp(self):
        run = self._run()
        apply_currency(run)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.CURRENT)
        self.assertIsNotNone(run.currency_checked_at)

    def test_outdated_reason_is_stored(self):
        run = self._run()
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        apply_currency(run)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)
        self.assertIn('Bahrain PDPL', run.outdated_reason)

    def test_outdated_reason_is_cleared_when_current_again(self):
        """A stale reason next to a Current badge is worse than none."""
        run = self._run()
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        apply_currency(run)
        self.assertTrue(run.outdated_reason)
        self.a.content_hash = 'a' * 64          # reverted
        self.a.save(update_fields=['content_hash'])
        apply_currency(run)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.CURRENT)
        self.assertEqual(run.outdated_reason, '')

    def test_repeated_checks_are_idempotent(self):
        run = self._run()
        apply_currency(run)
        first = run.currency_state
        for _ in range(3):
            apply_currency(run)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, first)

    def test_currency_never_changes_lifecycle(self):
        run = self._run(approve=True)
        before = (run.lifecycle, run.approved_at, run.version_no)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        apply_currency(run)
        run.refresh_from_db()
        self.assertEqual((run.lifecycle, run.approved_at, run.version_no), before)

    def test_currency_never_changes_result_lifecycles(self):
        run = self._run(results=3, approve=True)
        before = sorted(run.results.values_list('lifecycle', flat=True))
        apply_currency(run)
        self.assertEqual(sorted(run.results.values_list('lifecycle', flat=True)),
                         before)

    def test_currency_writes_no_feedback_records(self):
        run = self._run(approve=True)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        apply_currency(run)
        self.assertEqual(FeedbackSignal.objects.count(), 0)
        self.assertEqual(GoldExemplar.objects.count(), 0)

    def test_assess_is_pure_and_writes_nothing(self):
        run = self._run()
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        assess_currency(run)
        run.refresh_from_db()
        self.assertIsNone(run.currency_checked_at)
        self.assertEqual(run.outdated_reason, '')


class ReusabilityTests(_Base):

    def test_outdated_approved_run_is_not_reusable(self):
        run = self._run(approve=True)
        self.assertTrue(run.is_reusable)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        apply_currency(run)
        run.refresh_from_db()
        self.assertFalse(run.is_reusable)

    def test_unknown_approved_run_is_not_reusable(self):
        a = _doc('Unhashed', document_id='NH')
        run = self._run(a=a, approve=True)
        apply_currency(run)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.UNKNOWN)
        self.assertFalse(run.is_reusable)

    def test_unapproved_current_run_is_not_reusable(self):
        run = self._run()
        apply_currency(run)
        self.assertEqual(run.currency_state, CR.CURRENT)
        self.assertFalse(run.is_reusable)


class RefreshTests(_Base):

    def test_refresh_reports_counts_per_state(self):
        self._run(approve=True)
        a2 = _doc('Unhashed', document_id='NH')
        self._run(a=a2, approve=True)
        counts = refresh_approved_currency()
        self.assertEqual(counts[CR.CURRENT], 1)
        self.assertEqual(counts[CR.UNKNOWN], 1)

    def test_refresh_skips_unapproved_runs(self):
        run = self._run()
        refresh_approved_currency()
        run.refresh_from_db()
        self.assertIsNone(run.currency_checked_at)

    def test_one_failure_does_not_stop_the_rest(self):
        good = self._run(approve=True)
        bad = self._run(approve=True)
        bad.source_snapshot = {'reg_a': 'not-a-dict', 'reg_b': {}}
        bad.save(update_fields=['source_snapshot'])
        counts = refresh_currency_for([bad, good])
        self.assertEqual(counts[CR.CURRENT], 1)
        good.refresh_from_db()
        self.assertEqual(good.currency_state, CR.CURRENT)


# ═══════════════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════════════

class CurrencyPageTests(_Base):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('rev', password='x')
        self.client.force_login(self.user)

    def test_page_refreshes_currency_on_load(self):
        run = self._run(approve=True)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        self.client.get(reverse('comparison-approved'))
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)

    def test_page_shows_the_outdated_reason(self):
        self._run(approve=True)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'Outdated')
        self.assertContains(r, 'content has changed')

    def test_page_shows_checked_timestamp(self):
        self._run(approve=True)
        r = self.client.get(reverse('comparison-approved'))
        self.assertContains(r, 'checked')

    def test_outdated_run_loses_the_reuse_offer(self):
        self._run(approve=True)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        r = self.client.get(reverse('comparison-approved'))
        self.assertNotContains(r, 'Verified current')
        self.assertContains(r, 'Re-run comparison')

    def test_recheck_endpoint_updates_state(self):
        run = self._run(approve=True)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        r = self.client.post(
            reverse('comparison-run-recheck-currency', args=[run.pk]), follow=True)
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.OUTDATED)
        self.assertContains(r, 'content has changed')

    def test_recheck_reports_still_current(self):
        run = self._run(approve=True)
        r = self.client.post(
            reverse('comparison-run-recheck-currency', args=[run.pk]), follow=True)
        self.assertContains(r, 'still current')


class BackfillCommandTests(TestCase):

    def _run_cmd(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('backfill_content_hashes', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_dry_run_is_the_default_and_writes_nothing(self):
        doc = _doc('No file', document_id='NF')
        out = self._run_cmd()
        self.assertIn('DRY RUN', out)
        doc.refresh_from_db()
        self.assertEqual(doc.content_hash, '')

    def test_documents_without_a_file_are_reported_not_hashed(self):
        _doc('No file', document_id='NF')
        out = self._run_cmd()
        self.assertIn('no file attached', out)

    def test_existing_hashes_are_never_overwritten(self):
        doc = _doc('Already hashed', document_id='AH', content_hash='keep' * 16)
        self._run_cmd('--apply')
        doc.refresh_from_db()
        self.assertEqual(doc.content_hash, 'keep' * 16)

    def test_command_states_the_historical_limitation(self):
        out = self._run_cmd()
        self.assertIn('proves nothing about what a PAST comparison used', out)


class CheckCurrencyCommandTests(_Base):

    def _run_cmd(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('check_run_currency', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_dry_run_is_the_default(self):
        run = self._run(approve=True)
        out = self._run_cmd()
        self.assertIn('DRY RUN', out)
        run.refresh_from_db()
        self.assertIsNone(run.currency_checked_at)

    def test_apply_persists(self):
        run = self._run(approve=True)
        self._run_cmd('--apply')
        run.refresh_from_db()
        self.assertEqual(run.currency_state, CR.CURRENT)
        self.assertIsNotNone(run.currency_checked_at)

    def test_reports_the_outdated_reason(self):
        self._run(approve=True)
        self.a.content_hash = 'z' * 64
        self.a.save(update_fields=['content_hash'])
        out = self._run_cmd('--apply')
        self.assertIn('outdated', out)
        self.assertIn('content has changed', out)

    def test_flags_a_fingerprint_match_that_rests_on_missing_evidence(self):
        a = _doc('Unhashed A', document_id='NH-A')
        b = _doc('Unhashed B', document_id='NH-B', jurisdiction='india')
        self._run(a=a, b=b, approve=True)
        out = self._run_cmd()
        self.assertIn('not proof of sameness', out)

    def test_unknown_run_id_reports_cleanly(self):
        self.assertIn('No run with id 999999', self._run_cmd('999999'))
