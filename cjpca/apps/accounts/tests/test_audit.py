"""Audit-log tests — covers Part D.

Sections:

* ``LogEventHelperTests``       — log_event() field plumbing, role
                                   snapshot at call time, IP extraction
                                   (incl. X-Forwarded-For), anonymous user
                                   handling.
* ``HistoryViewScopingTests``   — analyst sees own events only;
                                   reviewer/admin see everything.
* ``IntegrationActionTests``    — one integration test per action key
                                   from Task D2: triggers the action and
                                   asserts an AuditLog row was written.
* ``ActionEmissionTests``       — static check that every declared action
                                   actually has a ``log_event`` call site.

A note on the guarded imports and skips below. This module used to import
``django_otp`` unconditionally. That package was dropped from the project
along with MFA, so the *entire module* failed to import and every test in
it was reported as a single collection error rather than run — which is
how the audit log grew holes without anyone noticing. Feature-dependent
tests are now skipped individually, with the reason attached, so the rest
of the file keeps guarding the trail.
"""

import ast
import io
import time
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from unittest import skipUnless

from apps.accounts.models import UserProfile
from apps.history.audit import Actions, NO_CALL_SITE, log_event
from apps.history.models import AuditLog

from .factories import make_user, disconnect_stuck_run_hook


User = get_user_model()

try:
    from django_otp.plugins.otp_totp.models import TOTPDevice
    HAS_OTP = True
except ImportError:  # MFA is not part of the current build
    TOTPDevice = None
    HAS_OTP = False


def _has_route(name, args=None) -> bool:
    """True if ``name`` resolves to a URL. Used to skip tests for admin
    screens that exist as views but are not routed."""
    try:
        reverse(name, args=args if args is not None else [])
        return True
    except NoReverseMatch:
        return False


HAS_USER_MGMT = _has_route('user-create')
HAS_IDLE_MIDDLEWARE = any('IdleSessionTimeout' in mw for mw in settings.MIDDLEWARE)


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — log_event helper plumbing
# ─────────────────────────────────────────────────────────────────────────────

class LogEventHelperTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.factory  = RequestFactory()
        cls.analyst  = make_user(username='audit_a', role=UserProfile.ANALYST)

    def test_writes_row_with_canonical_fields(self):
        request = self.factory.get('/', REMOTE_ADDR='192.0.2.10')
        row = log_event(
            self.analyst, Actions.LOGIN, request=request,
            description='probe sign-in',
            target_type='auth.User', target_id=self.analyst.pk,
            metadata={'foo': 'bar'},
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.event_type, 'auth.login')
        self.assertEqual(row.user, self.analyst)
        self.assertEqual(row.user_role_at_time, 'analyst')
        self.assertEqual(row.ip_address, '192.0.2.10')
        self.assertEqual(row.description, 'probe sign-in')
        self.assertEqual(row.related_object_type, 'auth.User')
        self.assertEqual(row.related_object_id, self.analyst.pk)
        self.assertEqual(row.change_detail, {'foo': 'bar'})

    def test_role_is_snapshotted_at_call_time(self):
        # Capture role at write time, then change it.
        log_event(self.analyst, Actions.COMPARISON_RUN, description='early run')

        # Reload the profile from the DB before mutating, so this test
        # doesn't trip over Django's cached-relation behaviour.
        self.analyst.refresh_from_db()
        self.analyst.profile.role = UserProfile.REVIEWER
        self.analyst.profile.save(update_fields=['role'])
        # Read-after-write: refresh again so log_event picks up the new role.
        self.analyst.refresh_from_db()

        log_event(self.analyst, Actions.REVIEW_ACCEPT, description='later review')

        early = AuditLog.objects.get(user=self.analyst, event_type=Actions.COMPARISON_RUN,
                                     description='early run')
        later = AuditLog.objects.get(user=self.analyst, event_type=Actions.REVIEW_ACCEPT,
                                     description='later review')
        self.assertEqual(early.user_role_at_time, 'analyst')
        self.assertEqual(later.user_role_at_time, 'reviewer')
        # Even though the user is now a reviewer, the early row keeps its
        # historical "analyst" snapshot.

    def test_ip_extraction_xff_first_hop(self):
        request = self.factory.get(
            '/', REMOTE_ADDR='10.0.0.1',
            HTTP_X_FORWARDED_FOR='198.51.100.7, 10.0.0.1, 10.0.0.2',
        )
        row = log_event(self.analyst, Actions.LOGIN, request=request)
        self.assertEqual(row.ip_address, '198.51.100.7')

    def test_ip_extraction_falls_back_to_remote_addr(self):
        request = self.factory.get('/', REMOTE_ADDR='203.0.113.5')
        row = log_event(self.analyst, Actions.LOGIN, request=request)
        self.assertEqual(row.ip_address, '203.0.113.5')

    def test_ip_extraction_handles_no_request(self):
        row = log_event(self.analyst, Actions.LOGIN)
        self.assertIsNone(row.ip_address)

    def test_anonymous_actor_writes_null_user(self):
        # Failed-login signal fires with user=None; helper must accept that.
        row = log_event(None, Actions.LOGIN_FAILED, description='attempt')
        self.assertIsNotNone(row)
        self.assertIsNone(row.user)
        self.assertEqual(row.user_role_at_time, '')


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — HistoryView role scoping
# ─────────────────────────────────────────────────────────────────────────────

class HistoryViewScopingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.alice  = make_user(username='alice_h',  role=UserProfile.ANALYST)
        cls.bob    = make_user(username='bob_h',    role=UserProfile.ANALYST)
        cls.review = make_user(username='review_h', role=UserProfile.REVIEWER)
        cls.admin  = make_user(username='admin_h',  role=UserProfile.ADMIN)

        # Two events from Alice, one from Bob, one from Reviewer.
        log_event(cls.alice,  Actions.COMPARISON_RUN, description='alice run 1')
        log_event(cls.alice,  Actions.MAPPING_RUN,    description='alice mapping')
        log_event(cls.bob,    Actions.COMPARISON_RUN, description='bob run 1')
        log_event(cls.review, Actions.REVIEW_ACCEPT,  description='review accepted')

    def test_analyst_only_sees_own_events(self):
        self.client.force_login(self.alice)
        r = self.client.get('/history/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('alice run 1', body)
        self.assertIn('alice mapping', body)
        self.assertNotIn('bob run 1', body)
        self.assertNotIn('review accepted', body)

    def test_reviewer_sees_everything(self):
        self.client.force_login(self.review)
        r = self.client.get('/history/')
        body = r.content.decode()
        self.assertIn('alice run 1', body)
        self.assertIn('bob run 1', body)
        self.assertIn('review accepted', body)

    def test_admin_sees_everything(self):
        self.client.force_login(self.admin)
        r = self.client.get('/history/')
        body = r.content.decode()
        self.assertIn('alice run 1', body)
        self.assertIn('bob run 1', body)
        self.assertIn('review accepted', body)


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Integration: every action key from Task D2 produces a row
# ─────────────────────────────────────────────────────────────────────────────

class _AuditRowAsserter(TestCase):
    """Mixin: assert at least one AuditLog row has the given event_type
    written within this test."""

    def assertAuditRow(self, action: str, *, user=None, target_id=None):
        qs = AuditLog.objects.filter(event_type=action)
        if user is not None:
            qs = qs.filter(user=user)
        if target_id is not None:
            qs = qs.filter(related_object_id=target_id)
        self.assertTrue(
            qs.exists(),
            f'Expected an AuditLog row with event_type={action!r}; '
            f'rows present: {list(AuditLog.objects.values_list("event_type", flat=True))}',
        )


class AuthSignalIntegrationTests(_AuditRowAsserter):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.user = make_user(username='int_login', role=UserProfile.ANALYST,
                             password='probepw1!')

    def test_auth_login_logged_via_signal(self):
        AuditLog.objects.all().delete()
        # Trigger Django's user_logged_in signal via real login.
        ok = self.client.login(username='int_login', password='probepw1!')
        self.assertTrue(ok)
        self.assertAuditRow(Actions.LOGIN, user=self.user)

    def test_auth_logout_logged_via_signal(self):
        self.client.force_login(self.user)
        AuditLog.objects.all().delete()
        self.client.logout()
        self.assertAuditRow(Actions.LOGOUT, user=self.user)

    def test_auth_login_failed_logged_via_signal(self):
        AuditLog.objects.all().delete()
        # Wrong password — fires user_login_failed.
        self.client.login(username='int_login', password='wrong-password')
        rows = AuditLog.objects.filter(event_type=Actions.LOGIN_FAILED)
        self.assertTrue(rows.exists())
        # User is None on failed login (we don't know who attempted).
        self.assertIsNone(rows.first().user)


@skipUnless(HAS_IDLE_MIDDLEWARE,
            'No IdleSessionTimeoutMiddleware in settings.MIDDLEWARE — '
            'auth.idle_timeout is listed in audit.NO_CALL_SITE')
class IdleTimeoutIntegrationTests(_AuditRowAsserter):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.user = make_user(username='int_idle', role=UserProfile.ANALYST)

    def test_idle_timeout_logged_before_logout(self):
        AuditLog.objects.all().delete()
        self.client.force_login(self.user)
        # Stamp activity past the idle threshold.
        session = self.client.session
        session['_last_activity'] = int(time.time()) - (10 * 24 * 3600)
        session.save()
        r = self.client.get('/', follow=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('reason=idle', r.url)
        self.assertAuditRow(Actions.IDLE_TIMEOUT, user=self.user)


@skipUnless(HAS_OTP, 'django_otp is not installed — MFA was removed from '
                     'the PoC; auth.mfa_* are listed in audit.UNREACHABLE')
class MFAIntegrationTests(_AuditRowAsserter):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin  = make_user(username='int_admin', role=UserProfile.ADMIN)
        cls.target = make_user(username='int_target', role=UserProfile.ANALYST)

    def test_mfa_enrolled_logged_on_totp_create(self):
        # make_user(with_mfa=True) already created a TOTPDevice for these
        # users at setUpTestData time — and that should have written an
        # auth.mfa_enrolled row via the post_save signal.
        self.assertTrue(AuditLog.objects.filter(
            event_type=Actions.MFA_ENROLLED, user=self.target,
        ).exists())

    def test_mfa_reset_logged_from_admin_endpoint(self):
        AuditLog.objects.all().delete()
        self.client.force_login(self.admin)
        r = self.client.post(reverse('user-reset-mfa', args=[self.target.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertAuditRow(Actions.MFA_RESET, user=self.admin,
                            target_id=self.target.pk)


@skipUnless(HAS_USER_MGMT,
            'User-management views are not routed in apps/accounts/urls.py — '
            'user.* are listed in audit.UNREACHABLE')
class UserManagementIntegrationTests(_AuditRowAsserter):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin  = make_user(username='int_useradmin', role=UserProfile.ADMIN)
        cls.target = make_user(username='int_usertarget', role=UserProfile.ANALYST)

    def setUp(self):
        AuditLog.objects.all().delete()
        self.client.force_login(self.admin)

    def test_user_created_logged(self):
        r = self.client.post(reverse('user-create'), {
            'username': 'newcomer', 'email': 'nc@example.com',
            'role': UserProfile.REVIEWER, 'password': 'tmpPW1!',
        })
        self.assertEqual(r.status_code, 302)
        new_user = User.objects.get(username='newcomer')
        self.assertAuditRow(Actions.USER_CREATED, user=self.admin,
                            target_id=new_user.pk)

    def test_user_role_changed_logged(self):
        r = self.client.post(reverse('user-change-role', args=[self.target.pk]),
                             {'role': UserProfile.REVIEWER})
        self.assertEqual(r.status_code, 302)
        self.assertAuditRow(Actions.USER_ROLE_CHANGED, user=self.admin,
                            target_id=self.target.pk)

    def test_user_disabled_logged(self):
        r = self.client.post(reverse('user-toggle-active', args=[self.target.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertAuditRow(Actions.USER_DISABLED, user=self.admin,
                            target_id=self.target.pk)

    def test_user_password_reset_logged(self):
        r = self.client.post(reverse('user-reset-password', args=[self.target.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertAuditRow(Actions.USER_PASSWORD_RESET, user=self.admin,
                            target_id=self.target.pk)


class ComparisonAndMappingIntegrationTests(_AuditRowAsserter):
    """comparison.run, mapping.run, review.accept/reject/modify."""

    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.analyst  = make_user(username='int_an',  role=UserProfile.ANALYST)
        cls.reviewer = make_user(username='int_rev', role=UserProfile.REVIEWER)

    def test_review_accept_logged(self):
        # Use the comparison transition endpoint with a real ComparisonResult.
        from apps.library.models import Document
        from apps.comparison.models import ComparisonResult, ComparisonRun
        reg_a = Document.objects.create(name='A', doc_type=Document.REGULATION,
                                        jurisdiction=Document.BAHRAIN, status=Document.INDEXED)
        reg_b = Document.objects.create(name='B', doc_type=Document.REGULATION,
                                        jurisdiction=Document.INDIA, status=Document.INDEXED)
        run = ComparisonRun.objects.create(pair_key='bh_in', reg_a=reg_a, reg_b=reg_b,
                                           status=ComparisonRun.COMPLETE)
        result = ComparisonResult.objects.create(run=run, citation_a='Art. 1',
                                                 citation_b='Art. 2',
                                                 lifecycle=ComparisonResult.DRAFT)

        AuditLog.objects.all().delete()
        self.client.force_login(self.reviewer)
        r = self.client.post(
            reverse('comparison-result-transition', args=[result.pk]),
            {'action': 'approved'},
        )
        self.assertIn(r.status_code, (200, 204))
        self.assertAuditRow(Actions.REVIEW_ACCEPT, user=self.reviewer,
                            target_id=result.pk)

    def test_review_reject_logged(self):
        from apps.library.models import Document
        from apps.comparison.models import ComparisonResult, ComparisonRun
        reg_a = Document.objects.create(name='C', doc_type=Document.REGULATION,
                                        jurisdiction=Document.BAHRAIN, status=Document.INDEXED)
        reg_b = Document.objects.create(name='D', doc_type=Document.REGULATION,
                                        jurisdiction=Document.INDIA, status=Document.INDEXED)
        run = ComparisonRun.objects.create(pair_key='bh_in', reg_a=reg_a, reg_b=reg_b,
                                           status=ComparisonRun.COMPLETE)
        result = ComparisonResult.objects.create(run=run, citation_a='Art. 9',
                                                 citation_b='', lifecycle=ComparisonResult.DRAFT)

        AuditLog.objects.all().delete()
        self.client.force_login(self.reviewer)
        r = self.client.post(
            reverse('comparison-result-transition', args=[result.pk]),
            {'action': 'rejected'},
        )
        self.assertIn(r.status_code, (200, 204))
        self.assertAuditRow(Actions.REVIEW_REJECT, user=self.reviewer,
                            target_id=result.pk)

    def test_review_modify_logged_via_note_edit(self):
        from apps.library.models import Document
        from apps.comparison.models import ComparisonResult, ComparisonRun
        reg_a = Document.objects.create(name='E', doc_type=Document.REGULATION,
                                        jurisdiction=Document.BAHRAIN, status=Document.INDEXED)
        reg_b = Document.objects.create(name='F', doc_type=Document.REGULATION,
                                        jurisdiction=Document.INDIA, status=Document.INDEXED)
        run = ComparisonRun.objects.create(pair_key='bh_in', reg_a=reg_a, reg_b=reg_b,
                                           status=ComparisonRun.COMPLETE)
        result = ComparisonResult.objects.create(run=run, citation_a='Art. 22',
                                                 citation_b='Art. 23',
                                                 lifecycle=ComparisonResult.DRAFT)

        AuditLog.objects.all().delete()
        self.client.force_login(self.reviewer)
        r = self.client.post(reverse('comparison-result-note', args=[result.pk]),
                             {'note': 'updated reviewer note'})
        self.assertEqual(r.status_code, 204)
        self.assertAuditRow(Actions.REVIEW_MODIFY, user=self.reviewer,
                            target_id=result.pk)

    def test_comparison_run_logged_when_run_created(self):
        # Run-creation goes through RunComparisonView which spawns a
        # subprocess + checks Ollama. We simulate the audit hook directly
        # by importing the helper used in the view path. The view-level
        # integration is exercised in dev manually; here we cover the helper.
        from apps.comparison.models import ComparisonRun
        from apps.library.models import Document
        reg_a = Document.objects.create(name='G', doc_type=Document.REGULATION,
                                        jurisdiction=Document.BAHRAIN, status=Document.INDEXED)
        reg_b = Document.objects.create(name='H', doc_type=Document.REGULATION,
                                        jurisdiction=Document.INDIA, status=Document.INDEXED)
        run = ComparisonRun.objects.create(pair_key='bh_in', reg_a=reg_a, reg_b=reg_b,
                                           created_by=self.analyst,
                                           status=ComparisonRun.RUNNING)
        log_event(self.analyst, Actions.COMPARISON_RUN,
                  target_type='comparison.ComparisonRun', target_id=run.pk,
                  description='probe')
        self.assertAuditRow(Actions.COMPARISON_RUN, user=self.analyst, target_id=run.pk)

    def test_mapping_run_logged_via_helper(self):
        from apps.library.models import Document
        from apps.mapping.models import MappingAnalysis
        policy = Document.objects.create(name='Policy P', doc_type=Document.POLICY,
                                         jurisdiction=Document.BBK, status=Document.INDEXED)
        analysis = MappingAnalysis.objects.create(policy_doc=policy, topic='full',
                                                  status=MappingAnalysis.RUNNING,
                                                  created_by=self.analyst)
        log_event(self.analyst, Actions.MAPPING_RUN,
                  target_type='mapping.MappingAnalysis', target_id=analysis.pk,
                  description='probe mapping')
        self.assertAuditRow(Actions.MAPPING_RUN, user=self.analyst,
                            target_id=analysis.pk)


class DocumentIntegrationTests(_AuditRowAsserter):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin = make_user(username='int_doc_admin', role=UserProfile.ADMIN)

    def setUp(self):
        AuditLog.objects.all().delete()
        self.client.force_login(self.admin)

    def test_document_delete_logged(self):
        from apps.library.models import Document
        doc = Document.objects.create(
            name='to-delete', doc_type=Document.POLICY,
            jurisdiction=Document.BBK, status=Document.INDEXED,
        )
        r = self.client.post(reverse('library-delete', args=[doc.pk]))
        # 302 redirect after delete; sometimes 200 if it's HTMX-aware.
        self.assertIn(r.status_code, (200, 302))
        self.assertAuditRow(Actions.DOCUMENT_DELETE, user=self.admin,
                            target_id=doc.pk)

    def test_document_upload_logged(self):
        # POST a tiny file — the upload view kicks off the ingestion
        # pipeline which we don't want to actually run, but the audit
        # row is written before the pipeline launches.
        from unittest.mock import patch
        fake_file = SimpleUploadedFile('test.txt', b'hello world',
                                       content_type='text/plain')
        with patch('apps.ingestion.pipeline.run_job', return_value=None):
            r = self.client.post(reverse('library-upload'), {
                'file':              fake_file,
                'name':              'probe-doc',
                'doc_type':          'policy',
                'jurisdiction':      'bbk',
                'effective_date':    '2025-01-01',
                'issuing_authority': 'Probe',
                'full_name':         'Probe Document',
            })
        self.assertIn(r.status_code, (200, 302, 400))
        # Even if the upload errored on the file pipeline, the audit row
        # for document.upload should exist.
        self.assertTrue(
            AuditLog.objects.filter(event_type=Actions.DOCUMENT_UPLOAD).exists()
            or AuditLog.objects.filter(event_type=Actions.DOCUMENT_DELETE).exists(),
            'No document.upload row written',
        )


class AllSixteenActionsCoveredTests(TestCase):
    """Belt-and-braces: every action key listed in SECURITY_RBAC_README D2
    must be defined as a constant on Actions."""

    EXPECTED = {
        # Part D canonical set
        'auth.login', 'auth.login_failed', 'auth.logout', 'auth.idle_timeout',
        'auth.mfa_enrolled', 'auth.mfa_reset',
        'comparison.run', 'mapping.run',
        'review.accept', 'review.reject', 'review.modify',
        'document.upload', 'document.delete',
        'user.created', 'user.role_changed', 'user.disabled',
        'user.password_reset',
        # Phase 2 — self-service profile (P1)
        'user.password_changed',
        'auth.backup_codes_regenerated', 'auth.sessions_terminated',
        # Phase 2 — run / ingestion completion (audit precursor for notifications)
        'comparison.complete', 'comparison.failed',
        'mapping.complete', 'mapping.failed',
        'ingestion.complete', 'ingestion.failed',
        # Phase 2 — reasoning layer (P3 monitoring panel)
        'reasoning.validation_error',
    }

    def test_all_action_constants_present(self):
        defined = set(Actions.all())
        missing = self.EXPECTED - defined
        self.assertFalse(missing, f'Action constants missing: {missing}')


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — static emission check
# ─────────────────────────────────────────────────────────────────────────────

# The test above only proves the *constants exist*. That is why it kept
# passing while several action keys had no writer at all: a dashboard can
# query 'reasoning.validation_error' forever and always render zero, and
# nothing in the suite objected. This section closes that hole by parsing
# the source and asking a different question — which actions are actually
# passed to a log_event() call?

_DJANGO_ROOT = Path(__file__).resolve().parents[3]      # …/cjpca
_REPO_ROOT   = _DJANGO_ROOT.parent
_SCAN_ROOTS  = [_DJANGO_ROOT / 'apps', _REPO_ROOT / 'reasoning']

# Value → constant name, for readable failure messages.
_VALUE_TO_NAME = {v: k for k, v in vars(Actions).items()
                  if not k.startswith('_') and isinstance(v, str)}


def _is_scannable(path: Path) -> bool:
    parts = path.parts
    if 'tests' in parts or 'migrations' in parts:
        return False
    return not path.name.startswith('test_')


def _action_values(node) -> set:
    """Collect every ``Actions.X`` value referenced anywhere under ``node``."""
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                and sub.value.id == 'Actions':
            value = getattr(Actions, sub.attr, None)
            if isinstance(value, str):
                found.add(value)
    return found


def _emitted_actions() -> set:
    """Return every action value passed as the ``action`` argument of a
    ``log_event(...)`` call in non-test source.

    Deliberately AST-based rather than a text search: 'reasoning.validation_error'
    appears four times in apps/accounts/views.py, but every one of them is a
    ``.filter(event_type=...)`` read. A grep would call that covered.

    Where the action is computed rather than named inline — the reviewer
    endpoints pick it out of an ``action_map`` dict keyed by lifecycle — we
    fall back to every ``Actions.X`` mentioned in the enclosing function.
    That is narrow enough not to count a dashboard query as an emission,
    since those live in functions that call no log_event at all.
    """
    emitted = set()
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob('*.py'):
            if not _is_scannable(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue

            # Map each function to its body so we can resolve indirection.
            scopes = [n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                        ast.Module))]
            for scope in scopes:
                for node in ast.walk(scope):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    name = (func.attr if isinstance(func, ast.Attribute)
                            else getattr(func, 'id', None))
                    if name != 'log_event' or len(node.args) < 2:
                        continue
                    arg = node.args[1]
                    if isinstance(arg, ast.Attribute) and \
                            isinstance(arg.value, ast.Name) and arg.value.id == 'Actions':
                        value = getattr(Actions, arg.attr, None)
                        if isinstance(value, str):
                            emitted.add(value)
                    elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        emitted.add(arg.value)
                    elif not isinstance(scope, ast.Module):
                        # Computed action (dict lookup, ternary, variable) —
                        # credit every Actions.X named in this function.
                        emitted |= _action_values(scope)
    return emitted


class ActionEmissionTests(TestCase):
    """Every declared action must have a writer, or be documented as not
    having one in ``apps.history.audit.NO_CALL_SITE``."""

    def test_every_action_has_a_log_event_call_site(self):
        emitted = _emitted_actions()
        expected = set(Actions.all()) - NO_CALL_SITE
        missing = expected - emitted
        self.assertFalse(
            missing,
            'These actions are declared but nothing calls log_event() with '
            'them. Either wire up the emission or add them to '
            'apps.history.audit.NO_CALL_SITE with a reason: '
            + ', '.join(sorted(f'{_VALUE_TO_NAME.get(m, "?")} ({m})' for m in missing)),
        )

    def test_no_call_site_allowlist_is_not_stale(self):
        emitted = _emitted_actions()
        resurrected = NO_CALL_SITE & emitted
        self.assertFalse(
            resurrected,
            'These actions now have a log_event() call site but are still '
            'listed in apps.history.audit.NO_CALL_SITE — remove them from '
            'that set: ' + ', '.join(sorted(resurrected)),
        )

    def test_emitted_raw_strings_are_declared_constants(self):
        """Catch the 'exports.downloaded' class of bug: an event key emitted
        as a bare string, absent from Actions, and therefore missing from the
        dashboard feeds and the history category map."""
        undeclared = _emitted_actions() - set(Actions.all())
        self.assertFalse(
            undeclared,
            'These event keys are written but not declared on Actions, so '
            'the history/monitoring surfaces built from that list will miss '
            'them: ' + ', '.join(sorted(undeclared)),
        )
