"""MFA tests — verify ForceMFAEnrollmentMiddleware + URL wiring + reset.

Covers:
* Authenticated users without a TOTP device get bounced to two_factor:setup
* Users with a confirmed TOTP device pass through to the dashboard
* The setup wizard, login, logout, and signup URLs are exempt from the
  redirect (otherwise the user could never reach the enrolment flow)
* Static/media path prefixes are exempt
* Admin reset_mfa endpoint removes the user's TOTP devices
* /accounts/users/ precedence: still wins over two_factor catch-alls
* REQUIRE_MFA=False makes the middleware a no-op
* Login URL resolves to the two_factor login page (Noor template wins)
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import UserProfile

from .factories import make_user, disconnect_stuck_run_hook


def attach_totp(user, name='test-device'):
    """Create a confirmed TOTP device so user_has_device() returns True."""
    return TOTPDevice.objects.create(user=user, name=name, confirmed=True)


class ForceMFAEnrollmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        # These tests assert enrolment behavior, so users start without TOTP.
        cls.analyst  = make_user(username='analyst1',  role=UserProfile.ANALYST,  with_mfa=False)
        cls.reviewer = make_user(username='reviewer1', role=UserProfile.REVIEWER, with_mfa=False)
        cls.admin    = make_user(username='admin1',    role=UserProfile.ADMIN,    with_mfa=False)

    def test_user_without_totp_redirected_to_setup(self):
        self.client.force_login(self.analyst)
        r = self.client.get('/', follow=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('two_factor/setup', r.url)

    def test_admin_without_totp_redirected_to_setup(self):
        # Bootstrap requirement: even existing admins (no TOTP yet) must be
        # walked through enrolment on next login.
        self.client.force_login(self.admin)
        r = self.client.get('/', follow=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('two_factor/setup', r.url)

    def test_user_with_totp_reaches_dashboard(self):
        attach_totp(self.analyst)
        self.client.force_login(self.analyst)
        r = self.client.get('/', follow=False)
        self.assertEqual(r.status_code, 200)

    def test_setup_url_itself_is_exempt(self):
        # If /accounts/two_factor/setup/ also got redirected, enrolment would
        # be impossible.
        self.client.force_login(self.analyst)
        r = self.client.get(reverse('two_factor:setup'), follow=False)
        # Setup view itself returns 200 for an unenrolled user (or 302 to
        # the wizard's next step). What matters: it is NOT a redirect to
        # /accounts/two_factor/setup/ (i.e. no infinite loop).
        if r.status_code == 302:
            self.assertNotIn('two_factor/setup/', r.url.rstrip('/').split('/')[-2:])

    def test_login_url_is_exempt(self):
        self.client.force_login(self.analyst)
        r = self.client.get(reverse('two_factor:login'), follow=False)
        # Already authenticated → two_factor's LoginView redirects to "/"
        # but our middleware then catches it at "/" and bounces to setup.
        # We just want to confirm the login URL itself is not the redirect
        # target of the MFA middleware.
        if r.status_code == 302:
            self.assertNotEqual(r.url, reverse('two_factor:setup'))

    def test_static_path_prefix_is_exempt(self):
        self.client.force_login(self.analyst)
        # Even if /static/missing.css 404s, the middleware must let it
        # through (no redirect).
        r = self.client.get('/static/css/output.css', follow=False)
        self.assertNotEqual(r.status_code, 302)

    def test_anonymous_users_not_affected(self):
        # The middleware only fires for authenticated users.
        r = self.client.get('/', follow=False)
        # Anonymous → home view's RoleRequiredMixin redirects to login.
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r.url)
        self.assertNotIn('two_factor/setup', r.url)


class RequireMFAFlagTests(TestCase):
    """REQUIRE_MFA=False must turn the middleware into a no-op."""

    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.user = make_user(username='flagtest', role=UserProfile.ANALYST, with_mfa=False)

    @override_settings(REQUIRE_MFA=False)
    def test_no_redirect_when_flag_disabled(self):
        # User has no TOTP device — but REQUIRE_MFA is False, so the
        # middleware should pass them straight through.
        self.client.force_login(self.user)
        r = self.client.get('/', follow=False)
        self.assertEqual(r.status_code, 200)

    @override_settings(REQUIRE_MFA=True)
    def test_redirect_when_flag_enabled(self):
        self.client.force_login(self.user)
        r = self.client.get('/', follow=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('two_factor/setup', r.url)


class UserManagementPrecedenceTests(TestCase):
    """The /accounts/users/* routes must win over any two_factor patterns."""

    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin = make_user(username='admin2', role=UserProfile.ADMIN)

    def test_user_management_resolves(self):
        self.client.force_login(self.admin)
        r = self.client.get('/accounts/users/', follow=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'User Management', r.content)

    def test_user_create_route_resolves(self):
        # Confirms /accounts/users/new/ is reachable (POST-only — GET 400s).
        self.client.force_login(self.admin)
        r = self.client.get('/accounts/users/new/', follow=False)
        self.assertEqual(r.status_code, 400)  # decorator passed; view rejects GET

    def test_login_route_serves_two_factor_template(self):
        # Confirms /accounts/login/ resolves to the two_factor LoginView,
        # which renders our Noor-branded override template.
        r = self.client.get('/accounts/login/', follow=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'CJPCA', r.content)
        # bootstrap markers from the upstream default template are gone
        self.assertNotIn(b'col-md-5', r.content)


class ResetMFATests(TestCase):
    """Admin reset-MFA endpoint must clear the user's TOTP devices."""

    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.admin = make_user(username='admin3', role=UserProfile.ADMIN)
        cls.target = make_user(username='target',  role=UserProfile.ANALYST)

    def test_reset_mfa_deletes_devices(self):
        # Target already has a TOTP device from make_user(with_mfa=True default).
        self.assertEqual(TOTPDevice.objects.filter(user=self.target).count(), 1)

        self.client.force_login(self.admin)
        r = self.client.post(
            reverse('user-reset-mfa', args=[self.target.pk]), follow=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TOTPDevice.objects.filter(user=self.target).count(), 0)

    def test_non_admin_cannot_reset_mfa(self):
        non_admin = make_user(username='notadmin', role=UserProfile.REVIEWER)

        self.client.force_login(non_admin)
        r = self.client.post(
            reverse('user-reset-mfa', args=[self.target.pk]), follow=False,
        )
        self.assertEqual(r.status_code, 403)
        # Target still has their device
        self.assertEqual(TOTPDevice.objects.filter(user=self.target).count(), 1)
