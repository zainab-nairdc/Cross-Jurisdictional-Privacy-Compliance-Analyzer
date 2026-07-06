"""
Integration tests for heatmap HTTP endpoints.

Run with:  python manage.py test apps.analytics.tests.test_endpoint
"""

import time

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.library.models import Document
from apps.mapping.models import MappingAnalysis, ObligationMapping

User = get_user_model()


# These tests predate the MFA + audit-log work in apps.accounts. They
# exercise the heatmap/gap-register endpoints with a vanilla username +
# password login, so we disable the force-MFA-enrolment middleware just
# for this module — without it every login() would be redirected to the
# TOTP setup wizard and the assertions would fail with 302 != 200.
_no_mfa = override_settings(REQUIRE_MFA=False)


def _make_user_with_full_visibility(username='testuser', password='pass'):
    """Create a User and promote them to ``admin`` role so the analytics
    queryset-level scoping doesn't filter the test fixtures away.

    The analytics endpoints scope analyst views to "own data only" — but
    these tests insert MappingAnalysis rows without a ``created_by`` set,
    expecting global visibility. Promoting to admin gives that visibility.
    """
    user = User.objects.create_user(username=username, password=password)
    # post_save signal already created the profile; flip it to admin.
    user.profile.role = 'admin'
    user.profile.save(update_fields=['role'])
    return user


def _make_doc(jurisdiction: str) -> Document:
    return Document.objects.create(
        name=f"Reg {jurisdiction}",
        jurisdiction=jurisdiction,
        doc_type=Document.REGULATION,
        status=Document.INDEXED,
    )


def _make_analysis(policy_doc: Document, topic: str) -> MappingAnalysis:
    return MappingAnalysis.objects.create(
        policy_doc=policy_doc,
        topic=topic,
        status=MappingAnalysis.APPROVED,
    )


def _make_ob(analysis, regulation, coverage="covered", title="Test obligation"):
    return ObligationMapping.objects.create(
        analysis=analysis,
        regulation=regulation,
        article_ref="Art. 1",
        obligation_title=title,
        coverage=coverage,
    )


@_no_mfa
class HeatmapDataViewTests(TestCase):
    """GET /analytics/heatmap/data/ — JSON data contract."""

    def setUp(self):
        self.user = _make_user_with_full_visibility(username="testuser", password="pass")
        self.client = Client()
        self.url = reverse("analytics-heatmap-data")

    def test_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (302, 403))

    def test_authenticated_returns_200(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_response_is_json(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_data_contract_shape(self):
        self.client.login(username="testuser", password="pass")
        data = self.client.get(self.url).json()

        self.assertIn("principles", data)
        self.assertIn("jurisdictions", data)
        self.assertIn("cells", data)
        self.assertEqual(len(data["cells"]), 33)

    def test_each_cell_has_required_keys(self):
        self.client.login(username="testuser", password="pass")
        data = self.client.get(self.url).json()
        required = {"principle", "jurisdiction", "total", "covered",
                    "partial", "not_covered", "coverage_pct", "status"}
        for cell in data["cells"]:
            self.assertEqual(set(cell.keys()), required)

    def test_cell_status_values_are_valid(self):
        self.client.login(username="testuser", password="pass")
        data = self.client.get(self.url).json()
        valid_statuses = {"green", "amber", "red", "grey"}
        for cell in data["cells"]:
            self.assertIn(cell["status"], valid_statuses)

    def test_response_time_under_500ms(self):
        self.client.login(username="testuser", password="pass")
        start = time.monotonic()
        self.client.get(self.url)
        elapsed_ms = (time.monotonic() - start) * 1000
        self.assertLess(elapsed_ms, 500, f"Response took {elapsed_ms:.0f}ms (limit 500ms)")

    def test_approved_obligations_reflected_in_data(self):
        policy = _make_doc("bahrain")
        reg_bh = _make_doc("bahrain")
        analysis = _make_analysis(policy, "Consent")
        _make_ob(analysis, reg_bh, "covered")

        self.client.login(username="testuser", password="pass")
        data = self.client.get(self.url).json()

        cell = next(
            c for c in data["cells"]
            if c["principle"] == "lawfulness_and_consent" and c["jurisdiction"] == "BH"
        )
        self.assertEqual(cell["total"], 1)
        self.assertEqual(cell["covered"], 1)
        self.assertIsNotNone(cell["coverage_pct"])


@_no_mfa
class HeatmapPartialViewTests(TestCase):
    """GET /analytics/heatmap/ — HTMX partial renders HTML."""

    def setUp(self):
        self.user = _make_user_with_full_visibility(username="testuser", password="pass")
        self.client = Client()
        self.url = reverse("analytics-heatmap")

    def test_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (302, 403))

    def test_authenticated_returns_200(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_returns_html_content(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url)
        self.assertIn("text/html", response["Content-Type"])

    def test_all_grey_renders_empty_state(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url)
        self.assertContains(response, "No approved mappings yet")

    def test_with_data_renders_hm_grid(self):
        policy = _make_doc("india")
        reg_in = _make_doc("india")
        analysis = _make_analysis(policy, "Security")
        _make_ob(analysis, reg_in, "covered")

        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url)
        self.assertContains(response, "hm-grid")
        self.assertContains(response, "hm-cell")

    def test_jurisdiction_codes_appear_in_grid(self):
        policy = _make_doc("bahrain")
        reg_bh = _make_doc("bahrain")
        analysis = _make_analysis(policy, "Consent")
        _make_ob(analysis, reg_bh, "covered")

        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url)
        for code in ("BH", "IN", "KW"):
            self.assertContains(response, code)


@_no_mfa
class GapRegisterViewTests(TestCase):
    """GET /analytics/gaps/ — HTMX partial: gap register."""

    def setUp(self):
        self.user = _make_user_with_full_visibility(username="testuser", password="pass")
        self.client = Client()
        self.url = reverse("analytics-gaps")

    def test_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (302, 403))

    def test_no_filter_returns_default_empty_state(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Click a heatmap cell")

    def test_filter_active_shows_badge_row(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url, {"jurisdiction": "BH", "principle": "retention"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bahrain")
        self.assertContains(response, "Retention")

    def test_unknown_jurisdiction_still_returns_200(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url, {"jurisdiction": "XX"})
        self.assertEqual(response.status_code, 200)

    def test_no_gaps_message_when_filter_active_but_empty(self):
        self.client.login(username="testuser", password="pass")
        response = self.client.get(self.url, {"jurisdiction": "KW", "principle": "accuracy"})
        self.assertContains(response, "No approved gaps")
