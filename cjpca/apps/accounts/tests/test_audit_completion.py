"""Audit-precursor tests — covers Commit 2a.

Verifies the new completion / failure audit events fire from the actual
finalization sites in the comparison, mapping, and ingestion runners. The
heavy AI/embedding/IO dependencies are stubbed so each test only exercises
the audit emission path (not the full RAG pipeline).

These events are the trigger for in-app notifications in Commit 2b
(apps.notifications). If audit emission breaks here, P2 silently stops
delivering "your run finished" messages — so a regression test per event
is worth the extra fixture noise.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.history.audit import Actions
from apps.history.models import AuditLog
from apps.library.models import Document

from .factories import disconnect_stuck_run_hook, make_user


User = get_user_model()


class ComparisonCompletionAuditTests(TestCase):
    """Drive _run_comparison_background through to its terminal states.

    The function does ``from reasoning.analyzer import compare_regulations``
    inside its try block, so patching the module-level attribute on
    ``reasoning.analyzer`` makes the runtime import pick up the stub.
    """

    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.analyst = make_user(username='cmp_audit_a', role=UserProfile.ANALYST)
        cls.reg_a = Document.objects.create(
            name='RegA', doc_type=Document.REGULATION,
            jurisdiction=Document.BAHRAIN, status=Document.INDEXED,
        )
        cls.reg_b = Document.objects.create(
            name='RegB', doc_type=Document.REGULATION,
            jurisdiction=Document.INDIA, status=Document.INDEXED,
        )

    def _make_run(self):
        from apps.comparison.models import ComparisonRun
        return ComparisonRun.objects.create(
            pair_key='bh_in', reg_a=self.reg_a, reg_b=self.reg_b,
            created_by=self.analyst, status=ComparisonRun.RUNNING,
        )

    def test_comparison_complete_logs_audit_event(self):
        from apps.comparison import views as cmp_views
        run = self._make_run()
        empty_report = SimpleNamespace(obligations=[])
        with patch('reasoning.workflows.compare_regulations', return_value=empty_report):
            cmp_views._run_comparison_background(run_pk=run.pk)
        self.assertEqual(
            AuditLog.objects.filter(
                user=self.analyst, event_type=Actions.COMPARISON_COMPLETE,
                related_object_id=run.pk,
            ).count(),
            1,
        )

    def test_comparison_failed_logs_audit_event(self):
        from apps.comparison import views as cmp_views
        run = self._make_run()
        with patch('reasoning.workflows.compare_regulations',
                   side_effect=RuntimeError('forced failure for test')):
            cmp_views._run_comparison_background(run_pk=run.pk)
        self.assertEqual(
            AuditLog.objects.filter(
                user=self.analyst, event_type=Actions.COMPARISON_FAILED,
                related_object_id=run.pk,
            ).count(),
            1,
        )


class MappingCompletionAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.analyst = make_user(username='map_audit_a', role=UserProfile.ANALYST)
        cls.policy = Document.objects.create(
            name='Policy P', doc_type=Document.POLICY,
            jurisdiction=Document.BBK, status=Document.INDEXED,
        )

    def _make_analysis(self):
        from apps.mapping.models import MappingAnalysis
        # No regulations attached → the inner per-reg loop is empty, so the
        # success branch fires without invoking the AI layer.
        return MappingAnalysis.objects.create(
            policy_doc=self.policy, topic='full',
            scope_mode=MappingAnalysis.SCOPE_FULL,
            status=MappingAnalysis.RUNNING, created_by=self.analyst,
        )

    def test_mapping_complete_logs_audit_event(self):
        from apps.mapping import views as map_views
        analysis = self._make_analysis()
        map_views._run_mapping_job(analysis_id=analysis.pk)
        self.assertEqual(
            AuditLog.objects.filter(
                user=self.analyst, event_type=Actions.MAPPING_COMPLETE,
                related_object_id=analysis.pk,
            ).count(),
            1,
        )

    def test_mapping_failed_logs_audit_event(self):
        # Force an exception inside the outer try block by patching the
        # early progress_total save to raise. The except branch flips status
        # to FAILED via .objects.filter().update() (different method, not
        # affected by the patch) and emits the audit row.
        from apps.mapping import views as map_views
        from apps.mapping.models import MappingAnalysis
        analysis = self._make_analysis()
        with patch.object(
            MappingAnalysis, 'save',
            side_effect=RuntimeError('forced failure for test'),
        ):
            map_views._run_mapping_job(analysis_id=analysis.pk)
        self.assertEqual(
            AuditLog.objects.filter(
                user=self.analyst, event_type=Actions.MAPPING_FAILED,
                related_object_id=analysis.pk,
            ).count(),
            1,
        )


class IngestionCompletionAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin = make_user(username='ing_audit_admin', role=UserProfile.ADMIN)

    def _make_doc_and_job(self, name='IngDoc', with_file=False):
        from apps.ingestion.models import IngestionJob
        doc_kwargs = {
            'name':         name,
            'doc_type':     Document.POLICY,
            'jurisdiction': Document.BBK,
            'status':       Document.PROCESSING,
        }
        if with_file:
            # _process_job calls Path(doc.file.path) before any patch fires,
            # so the document needs a real (tiny) file attached on disk.
            doc_kwargs['file'] = SimpleUploadedFile(
                f'{name}.txt', b'hello', content_type='text/plain',
            )
        doc = Document.objects.create(**doc_kwargs)
        job = IngestionJob.objects.create(
            document=doc, status=IngestionJob.QUEUED,
            current_stage=1, created_by=self.admin,
        )
        return doc, job

    def test_ingestion_failed_logs_audit_event(self):
        # _fail() is the central failure helper — exercised directly here so
        # the test does not need to stand up the entire pipeline.
        from apps.ingestion import pipeline
        _, job = self._make_doc_and_job()
        pipeline._fail(job, 'forced failure for test')
        self.assertEqual(
            AuditLog.objects.filter(
                user=self.admin, event_type=Actions.INGESTION_FAILED,
                related_object_id=job.pk,
            ).count(),
            1,
        )

    def test_ingestion_complete_logs_audit_event(self):
        # _process_job has 6 stages and heavy IO. Patch every loader /
        # embedder / indexer so the function takes the success branch
        # without touching Ollama or ChromaDB. The Document needs a real
        # file because Path(doc.file.path) is computed before any patch.
        from apps.ingestion import pipeline
        doc, job = self._make_doc_and_job(name='IngOK', with_file=True)
        fake_chunks = [{'node_id': 'n1', 'content': 'x'}]
        with patch.object(pipeline, '_set_stage'), \
             patch('ingestion.loaders.load_document', return_value='doc text'), \
             patch('ingestion.chunker.chunk_document', return_value=fake_chunks), \
             patch('ingestion.embedder.get_model'), \
             patch('ingestion.embedder.embed_chunks', return_value=[[0.0]]), \
             patch('ingestion.indexer.get_collection'), \
             patch('ingestion.indexer.index_chunks'), \
             patch('retrieval.bm25_store.upsert_chunks'), \
             patch('apps.comparison.concepts.compute_and_cache_doc_topics'):
            pipeline._process_job(job_id=job.pk)
        self.assertEqual(
            AuditLog.objects.filter(
                user=self.admin, event_type=Actions.INGESTION_COMPLETE,
                related_object_id=job.pk,
            ).count(),
            1,
        )
