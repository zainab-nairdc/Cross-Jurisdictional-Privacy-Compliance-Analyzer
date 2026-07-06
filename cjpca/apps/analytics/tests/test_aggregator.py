"""
Unit tests for coverage_heatmap() aggregator.

Run with:  python manage.py test apps.analytics.tests.test_aggregator
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.analytics.aggregators import (
    JURISDICTIONS,
    PRINCIPLES,
    coverage_heatmap,
)
from apps.library.models import Document
from apps.mapping.models import MappingAnalysis, ObligationMapping

User = get_user_model()


def _make_doc(jurisdiction: str) -> Document:
    return Document.objects.create(
        name=f"Reg {jurisdiction}",
        jurisdiction=jurisdiction,
        doc_type=Document.REGULATION,
        status=Document.INDEXED,
    )


def _make_analysis(policy_doc: Document, topic: str, status: str) -> MappingAnalysis:
    return MappingAnalysis.objects.create(
        policy_doc=policy_doc,
        topic=topic,
        status=status,
    )


def _make_ob(
    analysis: MappingAnalysis,
    regulation: Document,
    coverage: str,
    title: str = "Test obligation",
) -> ObligationMapping:
    return ObligationMapping.objects.create(
        analysis=analysis,
        regulation=regulation,
        article_ref="Art. 1",
        obligation_title=title,
        coverage=coverage,
    )


class CoverageHeatmapShapeTests(TestCase):
    """Always returns exactly 33 cells in the right shape."""

    def test_empty_db_returns_33_cells(self):
        data = coverage_heatmap()
        self.assertEqual(len(data["cells"]), 33)

    def test_principles_list_matches_constant(self):
        data = coverage_heatmap()
        self.assertEqual(data["principles"], PRINCIPLES)

    def test_jurisdictions_list_matches_constant(self):
        data = coverage_heatmap()
        self.assertEqual(data["jurisdictions"], JURISDICTIONS)

    def test_all_grey_when_no_approved_data(self):
        data = coverage_heatmap()
        for cell in data["cells"]:
            self.assertEqual(cell["status"], "grey", f"Expected grey for {cell}")
            self.assertIsNone(cell["coverage_pct"])

    def test_each_cell_has_required_keys(self):
        data = coverage_heatmap()
        required = {"principle", "jurisdiction", "total", "covered",
                    "partial", "not_covered", "coverage_pct", "status"}
        for cell in data["cells"]:
            self.assertEqual(set(cell.keys()), required)


class CoverageHeatmapFilteringTests(TestCase):
    """Only approved analyses are counted."""

    def setUp(self):
        self.policy = _make_doc("bahrain")
        self.reg_bh = _make_doc("bahrain")

    def test_non_approved_analysis_excluded(self):
        for status in (MappingAnalysis.RUNNING, MappingAnalysis.COMPLETE, MappingAnalysis.REVIEW):
            analysis = _make_analysis(self.policy, "Consent", status)
            _make_ob(analysis, self.reg_bh, ObligationMapping.COVERED)

        data = coverage_heatmap()
        for cell in data["cells"]:
            self.assertEqual(cell["total"], 0, f"Non-approved should not count: {cell}")

    def test_approved_analysis_included(self):
        analysis = _make_analysis(self.policy, "Consent", MappingAnalysis.APPROVED)
        _make_ob(analysis, self.reg_bh, ObligationMapping.COVERED)

        data = coverage_heatmap()
        bh_consent = next(
            c for c in data["cells"]
            if c["principle"] == "lawfulness_and_consent" and c["jurisdiction"] == "BH"
        )
        self.assertEqual(bh_consent["total"], 1)
        self.assertEqual(bh_consent["covered"], 1)


class CoverageHeatmapStatusBucketingTests(TestCase):
    """Status thresholds: green ≥ 80%, amber 40–79%, red < 40%."""

    def setUp(self):
        self.policy = _make_doc("bahrain")
        self.reg_bh = _make_doc("bahrain")

    def _make_consent_analysis(self):
        return _make_analysis(self.policy, "Consent", MappingAnalysis.APPROVED)

    def test_green_status_at_80_pct(self):
        analysis = self._make_consent_analysis()
        for _ in range(8):
            _make_ob(analysis, self.reg_bh, ObligationMapping.COVERED)
        for _ in range(2):
            _make_ob(analysis, self.reg_bh, ObligationMapping.NONE)

        data = coverage_heatmap()
        cell = next(c for c in data["cells"]
                    if c["principle"] == "lawfulness_and_consent" and c["jurisdiction"] == "BH")
        self.assertEqual(cell["status"], "green")
        self.assertEqual(cell["coverage_pct"], 80.0)

    def test_amber_status_between_40_and_79(self):
        analysis = self._make_consent_analysis()
        for _ in range(5):
            _make_ob(analysis, self.reg_bh, ObligationMapping.COVERED)
        for _ in range(5):
            _make_ob(analysis, self.reg_bh, ObligationMapping.NONE)

        data = coverage_heatmap()
        cell = next(c for c in data["cells"]
                    if c["principle"] == "lawfulness_and_consent" and c["jurisdiction"] == "BH")
        self.assertEqual(cell["status"], "amber")
        self.assertEqual(cell["coverage_pct"], 50.0)

    def test_red_status_below_40(self):
        analysis = self._make_consent_analysis()
        for _ in range(3):
            _make_ob(analysis, self.reg_bh, ObligationMapping.COVERED)
        for _ in range(7):
            _make_ob(analysis, self.reg_bh, ObligationMapping.NONE)

        data = coverage_heatmap()
        cell = next(c for c in data["cells"]
                    if c["principle"] == "lawfulness_and_consent" and c["jurisdiction"] == "BH")
        self.assertEqual(cell["status"], "red")
        self.assertEqual(cell["coverage_pct"], 30.0)

    def test_grey_when_total_is_zero(self):
        data = coverage_heatmap()
        cell = next(c for c in data["cells"]
                    if c["principle"] == "lawfulness_and_consent" and c["jurisdiction"] == "BH")
        self.assertEqual(cell["status"], "grey")
        self.assertIsNone(cell["coverage_pct"])


class CoverageHeatmapPartialWeightTests(TestCase):
    """Partial obligations count as 0.5 in coverage_pct."""

    def setUp(self):
        self.policy = _make_doc("india")
        self.reg_in = _make_doc("india")

    def test_partial_counts_as_half(self):
        analysis = _make_analysis(self.policy, "Consent", MappingAnalysis.APPROVED)
        _make_ob(analysis, self.reg_in, ObligationMapping.PARTIAL)
        _make_ob(analysis, self.reg_in, ObligationMapping.PARTIAL)

        data = coverage_heatmap()
        cell = next(c for c in data["cells"]
                    if c["principle"] == "lawfulness_and_consent" and c["jurisdiction"] == "IN")
        # (0 + 0.5*2) / 2 * 100 = 50.0
        self.assertEqual(cell["coverage_pct"], 50.0)
        self.assertEqual(cell["partial"], 2)
        self.assertEqual(cell["covered"], 0)

    def test_covered_plus_partial_plus_not_covered_equals_total(self):
        analysis = _make_analysis(self.policy, "Consent", MappingAnalysis.APPROVED)
        _make_ob(analysis, self.reg_in, ObligationMapping.COVERED)
        _make_ob(analysis, self.reg_in, ObligationMapping.PARTIAL)
        _make_ob(analysis, self.reg_in, ObligationMapping.NONE)
        _make_ob(analysis, self.reg_in, ObligationMapping.REVIEW)

        data = coverage_heatmap()
        cell = next(c for c in data["cells"]
                    if c["principle"] == "lawfulness_and_consent" and c["jurisdiction"] == "IN")
        self.assertEqual(
            cell["covered"] + cell["partial"] + cell["not_covered"],
            cell["total"],
        )


class CoverageHeatmapKeywordFallbackTests(TestCase):
    """Principle inference via obligation_title keyword when topic doesn't match."""

    def setUp(self):
        self.policy = _make_doc("kuwait")
        self.reg_kw = _make_doc("kuwait")

    def test_keyword_fallback_infers_data_minimization(self):
        # Topic "Compare all topics" won't match _TOPIC_TO_PRINCIPLE — falls back to title
        analysis = _make_analysis(self.policy, "Compare all topics", MappingAnalysis.APPROVED)
        _make_ob(analysis, self.reg_kw, ObligationMapping.COVERED,
                 title="Data minimisation requirements under PDPL")

        data = coverage_heatmap()
        cell = next(c for c in data["cells"]
                    if c["principle"] == "data_minimization" and c["jurisdiction"] == "KW")
        self.assertEqual(cell["total"], 1)

    def test_unknown_topic_and_title_excluded(self):
        analysis = _make_analysis(self.policy, "Unknown topic xyz", MappingAnalysis.APPROVED)
        _make_ob(analysis, self.reg_kw, ObligationMapping.COVERED,
                 title="Miscellaneous regulatory housekeeping")

        data = coverage_heatmap()
        for cell in data["cells"]:
            if cell["jurisdiction"] == "KW":
                self.assertEqual(cell["total"], 0,
                                 f"Unknown obligation should not appear in {cell['principle']}")

    def test_unknown_jurisdiction_excluded(self):
        reg_eu = _make_doc("eu")
        analysis = _make_analysis(self.policy, "Consent", MappingAnalysis.APPROVED)
        _make_ob(analysis, reg_eu, ObligationMapping.COVERED)

        data = coverage_heatmap()
        for cell in data["cells"]:
            self.assertEqual(cell["total"], 0, "EU jurisdiction should not appear in output")
