"""Profile page tests — Section 4.5 of MISSING_PAGES_README.

Covers:
* Anonymous redirect on /accounts/profile/.
* Each role can render its own profile (label + username appear).
* Password change posts an audit event.
* Backup-code regeneration replaces old codes with 10 fresh ones.

Uses ``make_user`` from ``factories`` plus a small helper for seeding the
StaticDevice + 10 StaticTokens that the regeneration test needs.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from django_otp.plugins.otp_static.models import StaticDevice, StaticToken

from apps.accounts.models import UserProfile
from apps.history.models import AuditLog

from .factories import disconnect_stuck_run_hook, make_user


User = get_user_model()


def _seed_backup_codes(user, count=10):
    """Create a confirmed StaticDevice + ``count`` StaticTokens for ``user``.

    Mirrors what the upstream two_factor backup-tokens flow leaves behind
    after a fresh enrolment, so the regeneration test exercises the
    delete-and-replace path rather than the blank-slate path.
    """
    device = StaticDevice.objects.create(user=user, name='backup', confirmed=True)
    for _ in range(count):
        StaticToken.objects.create(device=device, token=StaticToken.random_token())
    return device


class ProfileViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()

    def test_anonymous_redirects_to_login(self):
        r = self.client.get(reverse('profile'), follow=False)
        self.assertEqual(r.status_code, 302)
        # login_required redirects to LOGIN_URL with ?next=…
        self.assertIn('login', r.url.lower())

    def test_analyst_sees_own_profile(self):
        u = make_user(username='ana_pro', role=UserProfile.ANALYST)
        self.client.force_login(u)
        r = self.client.get(reverse('profile'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, u.username)
        self.assertContains(r, 'Compliance Analyst')

    def test_reviewer_sees_own_profile(self):
        u = make_user(username='rev_pro', role=UserProfile.REVIEWER)
        self.client.force_login(u)
        r = self.client.get(reverse('profile'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Legal Reviewer')

    def test_admin_sees_disable_mfa_link(self):
        # Admins get the live "Disable" link; non-admins get the "Contact admin"
        # placeholder. Verify both branches.
        admin = make_user(username='adm_pro', role=UserProfile.ADMIN)
        self.client.force_login(admin)
        r = self.client.get(reverse('profile'))
        self.assertContains(r, 'Administrator')
        self.assertContains(r, '/accounts/two_factor/disable/')

    def test_non_admin_sees_contact_admin_for_mfa_disable(self):
        u = make_user(username='ana_locked', role=UserProfile.ANALYST)
        self.client.force_login(u)
        r = self.client.get(reverse('profile'))
        self.assertContains(r, 'Contact admin')


class ChangePasswordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()

    def test_password_change_logs_audit_event(self):
        u = make_user(username='pw_user', role=UserProfile.ANALYST, password='OldPass123!')
        self.client.force_login(u)
        r = self.client.post(reverse('change-password'), {
            'old_password':  'OldPass123!',
            'new_password1': 'NewPass987!',
            'new_password2': 'NewPass987!',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            AuditLog.objects.filter(user=u, event_type='user.password_changed').count(),
            1,
        )
        # Verify the new password actually took.
        u.refresh_from_db()
        self.assertTrue(u.check_password('NewPass987!'))

    def test_password_change_with_wrong_old_password_does_not_log(self):
        u = make_user(username='pw_bad', role=UserProfile.ANALYST, password='OldPass123!')
        self.client.force_login(u)
        self.client.post(reverse('change-password'), {
            'old_password':  'WrongPass!!',
            'new_password1': 'NewPass987!',
            'new_password2': 'NewPass987!',
        })
        self.assertEqual(
            AuditLog.objects.filter(user=u, event_type='user.password_changed').count(),
            0,
        )


class BackupCodesRegenerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()

    def test_backup_codes_regeneration_replaces_old_codes(self):
        u = make_user(username='bc_user', role=UserProfile.ANALYST)
        _seed_backup_codes(u, count=10)
        self.assertEqual(StaticToken.objects.filter(device__user=u).count(), 10)

        self.client.force_login(u)
        r = self.client.post(reverse('regenerate-backup-codes'))
        self.assertEqual(r.status_code, 200)
        # Old device deleted, new one with 10 fresh tokens replaces it.
        self.assertEqual(StaticToken.objects.filter(device__user=u).count(), 10)
        # Audit row written.
        self.assertEqual(
            AuditLog.objects.filter(user=u, event_type='auth.backup_codes_regenerated').count(),
            1,
        )

    def test_backup_codes_response_shows_codes_once(self):
        u = make_user(username='bc_show', role=UserProfile.ANALYST)
        self.client.force_login(u)
        r = self.client.post(reverse('regenerate-backup-codes'))
        self.assertEqual(r.status_code, 200)
        # Exactly the 10 codes we just minted should appear in the response.
        codes = list(
            StaticToken.objects.filter(device__user=u).values_list('token', flat=True)
        )
        self.assertEqual(len(codes), 10)
        for c in codes:
            self.assertContains(r, c)
