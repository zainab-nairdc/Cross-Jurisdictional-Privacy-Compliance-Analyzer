"""RBAC tests — verify the role decorator + matrix gating.

Covers:
* Anonymous users redirected to login (302)
* analyst gets 403 on reviewer/admin-only pages
* reviewer gets 403 on analyst-only and admin-only pages
* admin reaches every page

The endpoint matrix mirrors Task A3 of SECURITY_RBAC_README.md.
"""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile

from .factories import make_user, disconnect_stuck_run_hook


class RBACMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        disconnect_stuck_run_hook()
        cls.analyst  = make_user(username='analyst1',  role=UserProfile.ANALYST)
        cls.reviewer = make_user(username='reviewer1', role=UserProfile.REVIEWER)
        cls.admin    = make_user(username='admin1',    role=UserProfile.ADMIN)

    # ── Anonymous ────────────────────────────────────────────────────────────

    def test_anonymous_home_redirects_to_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login/', r.url)

    # ── Home: open to all roles ──────────────────────────────────────────────

    def test_home_accessible_to_all_roles(self):
        for u in (self.analyst, self.reviewer, self.admin):
            with self.subTest(user=u.username):
                self.client.force_login(u)
                r = self.client.get('/')
                self.assertEqual(r.status_code, 200)

    # /ingestion/jobs/ tests removed: the page was deleted from the product.
    # Active ingestion observability now lives on the home dashboard widget
    # and the System Monitoring page (recent ingestion jobs panel).

    # ── /accounts/users/ → admin only ────────────────────────────────────────

    def test_analyst_cannot_access_user_management(self):
        self.client.force_login(self.analyst)
        self.assertEqual(self.client.get('/accounts/users/').status_code, 403)

    def test_reviewer_cannot_access_user_management(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get('/accounts/users/').status_code, 403)

    def test_admin_can_access_user_management(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/accounts/users/').status_code, 200)

    # ── /comparison/ index → all three roles ─────────────────────────────────

    def test_comparison_index_accessible_to_all_roles(self):
        for u in (self.analyst, self.reviewer, self.admin):
            with self.subTest(user=u.username):
                self.client.force_login(u)
                self.assertEqual(self.client.get('/comparison/').status_code, 200)

    # ── /comparison/<pair_key>/scope/ → analyst only ─────────────────────────

    def test_reviewer_cannot_run_comparison(self):
        self.client.force_login(self.reviewer)
        # bh_in is a real PAIR_CONFIGS key — even though regulations may not
        # exist yet, the decorator runs *before* the view body, so we get 403.
        self.assertEqual(self.client.get('/comparison/bh_in/scope/').status_code, 403)

    def test_admin_cannot_run_comparison(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/comparison/bh_in/scope/').status_code, 403)

    def test_analyst_can_open_comparison_scope(self):
        # The view itself may redirect away if no indexed regulations exist
        # (the spec's data-bearing flow), but it must NOT 403 for analyst.
        self.client.force_login(self.analyst)
        r = self.client.get('/comparison/bh_in/scope/')
        self.assertNotEqual(r.status_code, 403)

    # /comparison/custom/scope/ test removed: the route now 302's to the
    # combined /comparison/ landing page (the custom-scope picker UI was
    # inlined). Role enforcement still happens on /comparison/, covered by
    # test_comparison_index_accessible_to_all_roles above.

    # ── /mapping/ index → all three roles ────────────────────────────────────

    def test_mapping_index_accessible_to_all_roles(self):
        for u in (self.analyst, self.reviewer, self.admin):
            with self.subTest(user=u.username):
                self.client.force_login(u)
                self.assertEqual(self.client.get('/mapping/').status_code, 200)

    # ── /review/ → reviewer + admin only ─────────────────────────────────────

    def test_analyst_cannot_access_review(self):
        self.client.force_login(self.analyst)
        self.assertEqual(self.client.get('/review/').status_code, 403)

    def test_reviewer_can_access_review(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get('/review/').status_code, 200)

    def test_admin_can_access_review(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/review/').status_code, 200)

    # ── Library, history, analytics → all three roles ────────────────────────

    def test_library_regulations_accessible_to_all_roles(self):
        for u in (self.analyst, self.reviewer, self.admin):
            with self.subTest(user=u.username):
                self.client.force_login(u)
                self.assertEqual(self.client.get('/library/regulations/').status_code, 200)

    def test_library_policies_accessible_to_all_roles(self):
        for u in (self.analyst, self.reviewer, self.admin):
            with self.subTest(user=u.username):
                self.client.force_login(u)
                self.assertEqual(self.client.get('/library/policies/').status_code, 200)

    def test_history_accessible_to_all_roles(self):
        for u in (self.analyst, self.reviewer, self.admin):
            with self.subTest(user=u.username):
                self.client.force_login(u)
                self.assertEqual(self.client.get('/history/').status_code, 200)

    def test_analytics_accessible_to_all_roles(self):
        for u in (self.analyst, self.reviewer, self.admin):
            with self.subTest(user=u.username):
                self.client.force_login(u)
                self.assertEqual(self.client.get('/analytics/').status_code, 200)

    # ── Library write endpoints → admin only ─────────────────────────────────

    def test_analyst_cannot_upload_document(self):
        self.client.force_login(self.analyst)
        # We deliberately POST without a file; the decorator must 403 us
        # before the missing-file branch fires.
        self.assertEqual(self.client.post('/library/upload/').status_code, 403)

    def test_reviewer_cannot_upload_document(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.post('/library/upload/').status_code, 403)

    def test_admin_can_post_to_upload(self):
        self.client.force_login(self.admin)
        # Admin reaches the view body — the missing-file branch returns 400,
        # which proves the decorator passed.
        r = self.client.post('/library/upload/')
        self.assertEqual(r.status_code, 400)


class UserProfileSignalTests(TestCase):
    """The post_save signal must auto-create a UserProfile for new users."""

    def test_new_user_gets_profile_with_analyst_role(self):
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.create_user(username='fresh', password='pw')
        self.assertTrue(hasattr(u, 'profile'))
        self.assertEqual(u.profile.role, UserProfile.ANALYST)
