"""Phase D5 — a document that comparison work depends on cannot be deleted.

Two things are being fixed here, and the second matters more than the first.

  PROTECTION — `ComparisonRun.reg_a/reg_b` are PROTECT, so deleting a compared
  document can no longer silently destroy the assessment built on it.

  ORDER — `_purge_document()` used to drop the document's chunks from bm25,
  chroma and the Arabic store BEFORE deleting the row. A refused delete
  therefore left the Document in place with its searchable content already
  destroyed: a document that still reads as `indexed` and returns nothing. The
  reversible work now happens first, and `test_blocked_delete_leaves_chunks_intact`
  is the regression test for that.
"""

from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.comparison.assessments import approve_run, deletion_blockers, stamp_run
from apps.comparison.models import ComparisonResult as CRes, ComparisonRun as CR
from apps.feedback.models import FeedbackSignal, GoldExemplar
from apps.library.models import Document
from apps.library.views import (
    DocumentDeletionBlocked, _purge_document, document_deletion_blockers,
)


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
        self.free = _doc('Unreferenced Reg', document_id='FREE')

    def _run(self, a=None, b=None, approve=False, results=1):
        run = CR.objects.create(pair_key='p', reg_a=a or self.a,
                                reg_b=b or self.b, status=CR.COMPLETE)
        stamp_run(run, run.reg_a, run.reg_b)
        for i in range(results):
            CRes.objects.create(run=run, citation_a=f'Art {i}')
        if approve:
            run.results.update(lifecycle=CRes.APPROVED)
            approve_run(run)
        return run


# ═══════════════════════════════════════════════════════════════════════════
# D5.0 — blockers
# ═══════════════════════════════════════════════════════════════════════════

class BlockerTests(_Base):

    def test_unreferenced_document_has_no_blockers(self):
        self.assertEqual(deletion_blockers(self.free), [])

    def test_approved_assessment_is_a_blocker(self):
        self._run(approve=True)
        blockers = deletion_blockers(self.a)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]['kind'], 'approved_assessment')
        self.assertEqual(blockers[0]['severity'], 'hard')

    def test_draft_run_is_also_a_blocker(self):
        """Drafts are unfinished work, and deletion must not quietly take it."""
        self._run(approve=False)
        blockers = deletion_blockers(self.a)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]['kind'], 'comparison_run')
        self.assertEqual(blockers[0]['severity'], 'hard')

    def test_approved_and_draft_are_reported_separately(self):
        self._run(approve=True)
        self._run(approve=False)
        kinds = {b['kind'] for b in deletion_blockers(self.a)}
        self.assertEqual(kinds, {'approved_assessment', 'comparison_run'})

    def test_superseded_assessment_still_blocks(self):
        self._run(approve=True)
        self._run(approve=True)          # supersedes the first
        blockers = deletion_blockers(self.a)
        self.assertEqual(blockers[0]['kind'], 'approved_assessment')
        self.assertEqual(blockers[0]['count'], 2)

    def test_blocker_reports_which_side_the_document_was(self):
        self._run(a=self.a, b=self.b)
        self.assertEqual(deletion_blockers(self.a)[0]['runs'][0]['side'], 'A')
        self.assertEqual(deletion_blockers(self.b)[0]['runs'][0]['side'], 'B')

    def test_both_orientations_block(self):
        self._run(a=self.a, b=self.b, approve=True)
        self._run(a=self.b, b=self.a, approve=True)
        self.assertTrue(deletion_blockers(self.a))
        self.assertTrue(deletion_blockers(self.b))

    def test_unrelated_document_is_unaffected(self):
        self._run(a=self.a, b=self.b, approve=True)
        self.assertEqual(deletion_blockers(self.free), [])

    def test_blockers_are_pure(self):
        run = self._run(approve=True)
        before = (CR.objects.count(), run.lifecycle, Document.objects.count())
        deletion_blockers(self.a)
        run.refresh_from_db()
        self.assertEqual((CR.objects.count(), run.lifecycle,
                          Document.objects.count()), before)

    def test_none_and_unsaved_documents_are_handled(self):
        self.assertEqual(deletion_blockers(None), [])
        self.assertEqual(deletion_blockers(Document()), [])


# ═══════════════════════════════════════════════════════════════════════════
# D5.2 — database-level protection
# ═══════════════════════════════════════════════════════════════════════════

class ProtectTests(_Base):

    def test_direct_delete_of_a_referenced_document_is_refused(self):
        """The ORM-level guarantee: a shell, a script or the admin cannot
        bypass it either."""
        self._run(approve=True)
        with self.assertRaises(ProtectedError):
            self.a.delete()
        self.assertTrue(Document.objects.filter(pk=self.a.pk).exists())

    def test_direct_delete_is_refused_for_draft_runs_too(self):
        self._run(approve=False)
        with self.assertRaises(ProtectedError):
            self.a.delete()

    def test_unreferenced_document_deletes_directly(self):
        self.free.delete()
        self.assertFalse(Document.objects.filter(pk=self.free.pk).exists())

    def test_the_run_survives_a_refused_delete(self):
        run = self._run(approve=True, results=2)
        with self.assertRaises(ProtectedError):
            self.a.delete()
        run.refresh_from_db()
        self.assertEqual(run.lifecycle, CR.APPROVED)
        self.assertEqual(run.results.count(), 2)


# ═══════════════════════════════════════════════════════════════════════════
# D5.1 — refusal happens BEFORE anything destructive
# ═══════════════════════════════════════════════════════════════════════════

class PurgeOrderTests(_Base):

    def setUp(self):
        super().setUp()
        self.purged = []
        from retrieval import bm25_store
        from ingestion import indexer
        self._orig_bm, self._orig_ix = (bm25_store.delete_by_doc_title,
                                        indexer.delete_doc_chunks)
        bm25_store.delete_by_doc_title = lambda t: self.purged.append(('bm25', t))
        indexer.delete_doc_chunks = lambda t: self.purged.append(('chroma', t))
        self.addCleanup(setattr, bm25_store, 'delete_by_doc_title', self._orig_bm)
        self.addCleanup(setattr, indexer, 'delete_doc_chunks', self._orig_ix)

    def test_blocked_delete_leaves_chunks_intact(self):
        """THE regression test. Purging before deleting meant a refused delete
        destroyed a surviving document's searchable content."""
        self._run(approve=True)
        with self.assertRaises(DocumentDeletionBlocked):
            _purge_document(self.a)
        self.assertEqual(self.purged, [],
                         'chunks were purged for a document that was not deleted')
        self.assertTrue(Document.objects.filter(pk=self.a.pk).exists())

    def test_blocked_delete_raises_a_domain_error_not_protectederror(self):
        self._run(approve=True)
        with self.assertRaises(DocumentDeletionBlocked) as ctx:
            _purge_document(self.a)
        self.assertTrue(ctx.exception.blockers)
        self.assertIn('Bahrain PDPL', str(ctx.exception))

    def test_successful_delete_still_purges_chunks(self):
        _purge_document(self.free)
        self.assertFalse(Document.objects.filter(pk=self.free.pk).exists())
        self.assertEqual({kind for kind, _ in self.purged}, {'bm25', 'chroma'})

    def test_a_failing_store_does_not_resurrect_the_document(self):
        from retrieval import bm25_store

        def boom(_t):
            raise RuntimeError('bm25 down')
        bm25_store.delete_by_doc_title = boom
        _purge_document(self.free)
        self.assertFalse(Document.objects.filter(pk=self.free.pk).exists())

    def test_blocked_delete_does_not_write_an_audit_row(self):
        from apps.history.models import AuditLog
        self._run(approve=True)
        before = AuditLog.objects.count()
        with self.assertRaises(DocumentDeletionBlocked):
            _purge_document(self.a)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_blocked_delete_writes_no_feedback_records(self):
        self._run(approve=True)
        with self.assertRaises(DocumentDeletionBlocked):
            _purge_document(self.a, learning_mode='purge')
        self.assertEqual(FeedbackSignal.objects.count(), 0)
        self.assertEqual(GoldExemplar.objects.count(), 0)

    def test_document_deletion_blockers_wrapper_matches_the_service(self):
        self._run(approve=True)
        self.assertEqual(len(document_deletion_blockers(self.a)),
                         len(deletion_blockers(self.a)))


# ═══════════════════════════════════════════════════════════════════════════
# D5.1 / D5.3 — the UI
# ═══════════════════════════════════════════════════════════════════════════

class DeleteViewTests(_Base):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('admin', password='x',
                                             is_superuser=True)
        self.client.force_login(self.user)

    def test_confirm_page_lists_the_blockers(self):
        self._run(approve=True)
        r = self.client.get(reverse('library-delete', args=[self.a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'cannot be deleted')
        self.assertContains(r, 'approved comparison assessment')

    def test_confirm_page_links_the_blocking_runs(self):
        run = self._run(approve=True)
        r = self.client.get(reverse('library-delete', args=[self.a.pk]))
        self.assertContains(r, reverse('comparison-workspace', args=[run.pk]))

    def test_confirm_page_disables_the_delete_button(self):
        self._run(approve=True)
        r = self.client.get(reverse('library-delete', args=[self.a.pk]))
        self.assertContains(r, 'Resolve the dependencies listed above first')

    def test_confirm_page_for_a_free_document_offers_deletion(self):
        r = self.client.get(reverse('library-delete', args=[self.free.pk]))
        self.assertNotContains(r, 'cannot be deleted')
        self.assertContains(r, 'This action cannot be undone')

    def test_posting_a_blocked_delete_returns_a_message_not_a_500(self):
        """Previously an uncaught ProtectedError produced a 500."""
        self._run(approve=True)
        r = self.client.post(reverse('library-delete', args=[self.a.pk]),
                             follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Document.objects.filter(pk=self.a.pk).exists())
        self.assertContains(r, 'cannot be deleted')

    def test_posting_a_blocked_delete_preserves_the_assessment(self):
        run = self._run(approve=True, results=2)
        self.client.post(reverse('library-delete', args=[self.a.pk]), follow=True)
        run.refresh_from_db()
        self.assertEqual(run.lifecycle, CR.APPROVED)
        self.assertEqual(run.results.count(), 2)

    def test_posting_a_free_delete_still_works(self):
        self.client.post(reverse('library-delete', args=[self.free.pk]))
        self.assertFalse(Document.objects.filter(pk=self.free.pk).exists())

    def test_htmx_blocked_delete_redirects_instead_of_500(self):
        self._run(approve=True)
        r = self.client.post(reverse('library-delete', args=[self.a.pk]),
                             HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 200)
        self.assertIn('HX-Redirect', r)
        self.assertTrue(Document.objects.filter(pk=self.a.pk).exists())

    def test_deleting_a_missing_document_is_still_harmless(self):
        r = self.client.post(reverse('library-delete', args=[999999]))
        self.assertIn(r.status_code, (200, 302))


class NonInterferenceTests(_Base):
    """D5 must not disturb anything else."""

    def test_currency_state_is_untouched_by_a_blocked_delete(self):
        run = self._run(approve=True)
        before = (run.currency_state, run.outdated_reason)
        with self.assertRaises(DocumentDeletionBlocked):
            _purge_document(self.a)
        run.refresh_from_db()
        self.assertEqual((run.currency_state, run.outdated_reason), before)

    def test_supersession_still_works_on_a_referenced_document(self):
        """Superseding is not deleting — it must remain available."""
        run = self._run(approve=True)
        newer = _doc('Bahrain PDPL 2026', document_id='BH-PDPL')
        self.a.supersede_with(newer)
        self.a.refresh_from_db(); run.refresh_from_db()
        self.assertTrue(self.a.superseded)
        self.assertEqual(run.currency_state, CR.OUTDATED)

    def test_legacy_comparison_analysis_still_cascades(self):
        """Left on CASCADE deliberately — legacy, and carries no approval."""
        from apps.comparison.models import ComparisonAnalysis
        ca = ComparisonAnalysis.objects.create(reg_a=self.free, reg_b=self.b,
                                               topic='t')
        self.free.delete()
        self.assertFalse(ComparisonAnalysis.objects.filter(pk=ca.pk).exists())
