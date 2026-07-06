"""System monitoring page tests — Section 6 of MISSING_PAGES_README.

Two themes:

1. **Role gating.** Anonymous → 302 to login. Analyst → 403. Reviewer →
   403. Admin → 200 with all six panels in context.
2. **Graceful degradation.** The page's whole purpose is to surface
   infrastructure problems — including its own dependencies failing.
   Every panel must render an "unreachable" / "error" badge instead of
   crashing the page when its underlying service is down. We patch
   ``requests.get`` (Ollama), ``ingestion.indexer.get_collection``
   (ChromaDB), and the BM25 path to simulate each failure independently.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.accounts.tests.factories import disconnect_stuck_run_hook, make_user


User = get_user_model()


URL = '/accounts/admin/monitoring/'


# ─────────────────────────────────────────────────────────────────────────────
# Role gating
# ─────────────────────────────────────────────────────────────────────────────


class MonitoringRoleGatingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.analyst  = make_user(username='mon_a',  role=UserProfile.ANALYST)
        cls.reviewer = make_user(username='mon_r',  role=UserProfile.REVIEWER)
        cls.admin    = make_user(username='mon_ad', role=UserProfile.ADMIN)

    def test_anonymous_redirects_to_login(self):
        r = self.client.get(URL, follow=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r.url.lower())

    def test_analyst_forbidden(self):
        self.client.force_login(self.analyst)
        r = self.client.get(URL, follow=False)
        self.assertEqual(r.status_code, 403)

    def test_reviewer_forbidden(self):
        self.client.force_login(self.reviewer)
        r = self.client.get(URL, follow=False)
        self.assertEqual(r.status_code, 403)

    def test_admin_can_access(self):
        self.client.force_login(self.admin)
        # Patch the heavy infra so the test doesn't actually call Ollama
        # or open ChromaDB. The graceful-degrade tests below cover the
        # real-error paths; here we just want the 200 + context shape.
        with self._stub_all_panels_healthy():
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        for key in (
            'ollama', 'chroma', 'bm25', 'sessions',
            'audit_log_volume', 'recent_ingestion_jobs',
            'recent_validation_errors',
        ):
            self.assertIn(key, r.context)

    def _stub_all_panels_healthy(self):
        """Context manager that stubs every external dep to a healthy mock.

        Used by the role-gating happy path — the graceful-degrade tests
        patch individual panels to raise instead.
        """
        from contextlib import ExitStack
        stack = ExitStack()

        # Ollama: 200 OK with one model.
        ollama_resp = type('R', (), {
            'raise_for_status': lambda self: None,
            'json': lambda self: {'models': [{'name': 'llama3.2:1b'}]},
            'elapsed': type('E', (), {'total_seconds': lambda self: 0.025})(),
        })()
        stack.enter_context(patch('requests.get', return_value=ollama_resp))

        # ChromaDB: collection exists with a known count.
        fake_coll = type('C', (), {'count': lambda self: 42})()
        stack.enter_context(patch('ingestion.indexer.get_collection', return_value=fake_coll))

        # BM25: pretend the file is missing, so the panel renders the
        # "missing" badge without trying to connect to a real DB. The
        # graceful-degrade test below covers this path explicitly.
        stack.enter_context(patch('os.path.exists', return_value=False))

        return stack


# ─────────────────────────────────────────────────────────────────────────────
# Graceful degradation — each external dep failing must NOT crash the page
# ─────────────────────────────────────────────────────────────────────────────


class MonitoringGracefulDegradationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin = make_user(username='mon_grace_admin', role=UserProfile.ADMIN)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_ollama_unreachable_renders_unreachable_badge(self):
        with patch('requests.get', side_effect=Exception('connection refused')):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['ollama']['status'], 'unreachable')
        self.assertIn('connection refused', r.context['ollama']['error'])
        self.assertContains(r, 'UNREACHABLE')

    def test_chroma_error_renders_error_badge(self):
        with patch('ingestion.indexer.get_collection',
                   side_effect=Exception('chroma sqlite locked')):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['chroma']['status'], 'error')
        self.assertIn('chroma sqlite locked', r.context['chroma']['error'])

    def test_bm25_missing_file_renders_missing_badge(self):
        # Simulate the FTS5 DB not existing on disk.
        with patch('os.path.exists', return_value=False):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['bm25']['status'], 'missing')
        self.assertContains(r, 'MISSING')

    def test_bm25_corrupt_db_renders_error_badge(self):
        # File exists but the SQLite open / query raises.
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024), \
             patch('sqlite3.connect', side_effect=Exception('database disk image is malformed')):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['bm25']['status'], 'error')

    def test_all_three_infra_failing_simultaneously_still_renders(self):
        # The strongest version of the contract: every external dep is
        # down at once. The page must STILL load with sensible badges.
        with patch('requests.get', side_effect=Exception('ollama down')), \
             patch('ingestion.indexer.get_collection', side_effect=Exception('chroma down')), \
             patch('os.path.exists', return_value=False):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['ollama']['status'], 'unreachable')
        self.assertEqual(r.context['chroma']['status'], 'error')
        self.assertEqual(r.context['bm25']['status'], 'missing')


# ─────────────────────────────────────────────────────────────────────────────
# Audit log volume + reasoning validation errors
# ─────────────────────────────────────────────────────────────────────────────


class MonitoringDataPanelsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin = make_user(username='mon_data', role=UserProfile.ADMIN)

    def test_audit_log_volume_counts_present(self):
        # Seed a few audit rows so the counters are non-zero. The view
        # tolerates infra failures (BM25, ChromaDB, Ollama) — patch them
        # all out so this test focuses on the audit panel.
        from apps.history.audit import Actions, log_event
        for _ in range(3):
            log_event(self.admin, Actions.LOGIN, description='probe')
        self.client.force_login(self.admin)
        with patch('requests.get', side_effect=Exception('skip')), \
             patch('ingestion.indexer.get_collection', side_effect=Exception('skip')), \
             patch('os.path.exists', return_value=False):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        vol = r.context['audit_log_volume']
        self.assertEqual(vol['status'], 'healthy')
        self.assertGreaterEqual(vol['last_24h'], 3)
        self.assertGreaterEqual(vol['total'], 3)

    def test_recent_validation_errors_picked_up_from_audit_log(self):
        from apps.history.audit import Actions, log_event
        log_event(
            None, Actions.REASONING_VALIDATION_ERROR,
            description='Reasoning (comparison) parse failed',
            metadata={'kind': 'comparison', 'error_type': 'ValidationError'},
        )
        self.client.force_login(self.admin)
        with patch('requests.get', side_effect=Exception('skip')), \
             patch('ingestion.indexer.get_collection', side_effect=Exception('skip')), \
             patch('os.path.exists', return_value=False):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        rows = r.context['recent_validation_errors']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].change_detail['kind'], 'comparison')

    def test_empty_validation_error_panel_renders_friendly_message(self):
        self.client.force_login(self.admin)
        with patch('requests.get', side_effect=Exception('skip')), \
             patch('ingestion.indexer.get_collection', side_effect=Exception('skip')), \
             patch('os.path.exists', return_value=False):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['recent_validation_errors']), 0)
        self.assertContains(r, 'No recent validation errors')


# ─────────────────────────────────────────────────────────────────────────────
# HTMX poll — the fragment-only response when request is HTMX-driven
# ─────────────────────────────────────────────────────────────────────────────


class MonitoringHTMXFragmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin = make_user(username='mon_htmx', role=UserProfile.ADMIN)

    def test_htmx_request_returns_panels_fragment_only(self):
        # An HTMX-driven poll should not re-render the sidebar / page chrome.
        self.client.force_login(self.admin)
        with patch('requests.get', side_effect=Exception('skip')), \
             patch('ingestion.indexer.get_collection', side_effect=Exception('skip')), \
             patch('os.path.exists', return_value=False):
            r = self.client.get(URL, HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 200)
        # Fragment carries the panels container but no <html> chrome.
        self.assertContains(r, 'monitoring-panels')
        self.assertNotContains(r, '<html')
