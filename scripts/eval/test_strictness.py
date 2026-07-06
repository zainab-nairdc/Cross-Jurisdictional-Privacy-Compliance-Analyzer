"""
Unit tests for apps/comparison/strictness.py — Visual 9 Jurisdictional Strictness Meter.
Run with: python -m pytest tests/unit/test_strictness.py -v  (from repo root)
"""
import sys
import os
import django

# ── Django setup ────────────────────────────────────────────────────────────────
ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "cjpca")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cjpca.settings")
django.setup()

import pytest
from unittest.mock import patch, MagicMock

from apps.comparison.strictness import (
    MANDATORY_VERB_PATTERN,
    NUMERIC_THRESHOLD_PATTERN,
    _classify_penalty_language,
    _compute_specificity,
    _score_tier,
    compute_strictness_score,
    StrictnessResult,
    TIER_BAR_COLOR,
)


# ── Pattern tests ───────────────────────────────────────────────────────────────

class TestMandatoryVerbPattern:
    def test_matches_shall(self):
        assert MANDATORY_VERB_PATTERN.search("The controller shall notify")

    def test_matches_must(self):
        assert MANDATORY_VERB_PATTERN.search("Data must be accurate")

    def test_matches_may_not(self):
        assert MANDATORY_VERB_PATTERN.search("Processors may not transfer data")

    def test_matches_is_required_to(self):
        assert MANDATORY_VERB_PATTERN.search("The entity is required to report")

    def test_matches_must_not(self):
        assert MANDATORY_VERB_PATTERN.search("Controllers must not retain data beyond")

    def test_case_insensitive(self):
        assert MANDATORY_VERB_PATTERN.search("The DPO SHALL be consulted")

    def test_no_false_positive_should(self):
        # "should" is advisory, not mandatory — must NOT match
        assert not MANDATORY_VERB_PATTERN.search("Controllers should consider privacy.")

    def test_counts_multiple(self):
        text = "Controllers shall notify. Processors must document. Data may not leave."
        assert len(MANDATORY_VERB_PATTERN.findall(text)) == 3


class TestNumericThresholdPattern:
    def test_matches_days(self):
        assert NUMERIC_THRESHOLD_PATTERN.search("notify within 72 hours")

    def test_matches_percentage(self):
        assert NUMERIC_THRESHOLD_PATTERN.search("a fine of up to 4%")

    def test_matches_currency(self):
        assert NUMERIC_THRESHOLD_PATTERN.search("not exceeding 100000 BHD")

    def test_matches_months(self):
        assert NUMERIC_THRESHOLD_PATTERN.search("retention period of 36 months")

    def test_matches_working_days(self):
        assert NUMERIC_THRESHOLD_PATTERN.search("response within 30 working days")

    def test_counts_multiple(self):
        text = "Notify within 72 hours. Retain for 5 years. Fine: 10% of revenue."
        assert len(NUMERIC_THRESHOLD_PATTERN.findall(text)) == 3


# ── Penalty classification ──────────────────────────────────────────────────────

class TestClassifyPenalty:
    def test_severe(self):
        assert _classify_penalty_language("subject to imprisonment for breach") == "severe"

    def test_moderate(self):
        assert _classify_penalty_language("fine not exceeding BHD 20,000") == "moderate"

    def test_minor(self):
        assert _classify_penalty_language("may receive a warning notice") == "minor"

    def test_none(self):
        assert _classify_penalty_language("data controllers should maintain records") == "none"

    def test_severe_beats_moderate(self):
        assert _classify_penalty_language("imprisonment or fine not exceeding 10000") == "severe"


# ── Specificity ratio ───────────────────────────────────────────────────────────

class TestComputeSpecificity:
    def test_all_specific(self):
        text = "Controllers shall notify the authority. Processors must document transfers."
        ratio = _compute_specificity(text)
        assert ratio == 1.0

    def test_none_specific(self):
        text = "Data is important. Privacy matters. This regulation applies to controllers."
        ratio = _compute_specificity(text)
        assert ratio == 0.0

    def test_half_specific(self):
        text = "Data is important. Controllers shall report breaches."
        ratio = _compute_specificity(text)
        assert 0.4 < ratio < 0.7

    def test_empty_text(self):
        assert _compute_specificity("") == 0.0


# ── Score tier mapping ──────────────────────────────────────────────────────────

class TestScoreTier:
    @pytest.mark.parametrize("score,expected", [
        (0.0, "lenient"),
        (3.9, "lenient"),
        (4.0, "moderate"),
        (6.9, "moderate"),
        (7.0, "strict"),
        (8.4, "strict"),
        (8.5, "severe"),
        (10.0, "severe"),
    ])
    def test_tier_boundaries(self, score, expected):
        assert _score_tier(score) == expected


# ── compute_strictness_score (mocked DB) ────────────────────────────────────────

class TestComputeStrictnessScore:
    RICH_TEXT = (
        "The data controller shall notify the supervisory authority within 72 hours of "
        "becoming aware of a personal data breach. The processor must document all "
        "processing activities. Transfer of data may not occur without adequate safeguards. "
        "A fine not exceeding BHD 20,000 may be imposed. The controller is required to "
        "appoint a Data Protection Officer. Data must not be retained beyond 5 years. "
        "Entities shall implement technical measures. Records shall be kept for 3 years. "
        "Processors are required to conduct impact assessments. Controllers must not "
        "process sensitive data without explicit consent."
    )

    def _mock_doc(self, pk=1, name="Test Regulation"):
        doc = MagicMock()
        doc.pk = pk
        doc.name = name
        doc.full_name = name
        return doc

    @patch("apps.comparison.strictness._get_full_text")
    @patch("apps.library.models.Document.objects.get")
    def test_returns_strictness_result(self, mock_get, mock_text):
        mock_get.return_value = self._mock_doc()
        mock_text.return_value = self.RICH_TEXT

        result = compute_strictness_score(1)

        assert isinstance(result, StrictnessResult)
        assert 0.0 <= result.score <= 10.0
        assert result.score_tier in ("lenient", "moderate", "strict", "severe")
        assert result.bar_color in TIER_BAR_COLOR.values()

    @patch("apps.comparison.strictness._get_full_text")
    @patch("apps.library.models.Document.objects.get")
    def test_all_four_components_present(self, mock_get, mock_text):
        mock_get.return_value = self._mock_doc()
        mock_text.return_value = self.RICH_TEXT

        result = compute_strictness_score(1)

        assert "mandatory_verb_density" in result.components
        assert "numeric_thresholds" in result.components
        assert "penalty_severity" in result.components
        assert "specificity_ratio" in result.components

    @patch("apps.comparison.strictness._get_full_text")
    @patch("apps.library.models.Document.objects.get")
    def test_weights_sum_to_score(self, mock_get, mock_text):
        mock_get.return_value = self._mock_doc()
        mock_text.return_value = self.RICH_TEXT

        result = compute_strictness_score(1)
        comps = result.components
        total_contribution = sum(c.contribution for c in comps.values())
        # total contributions × 10 ≈ score (within float rounding)
        assert abs(total_contribution * 10 - result.score) < 0.2

    @patch("apps.comparison.strictness._get_full_text")
    @patch("apps.library.models.Document.objects.get")
    def test_empty_text_returns_zero_score(self, mock_get, mock_text):
        mock_get.return_value = self._mock_doc()
        mock_text.return_value = ""

        result = compute_strictness_score(1)

        assert result.score == 0.0
        assert result.summary_line == "No text analyzed yet"

    @patch("apps.comparison.strictness._get_full_text")
    @patch("apps.library.models.Document.objects.get")
    def test_reproducibility(self, mock_get, mock_text):
        mock_get.return_value = self._mock_doc()
        mock_text.return_value = self.RICH_TEXT

        result_a = compute_strictness_score(1)
        result_b = compute_strictness_score(1)

        assert result_a.score == result_b.score
        assert result_a.score_tier == result_b.score_tier

    @patch("apps.comparison.strictness._get_full_text")
    @patch("apps.library.models.Document.objects.get")
    def test_bar_width_pct_matches_score(self, mock_get, mock_text):
        mock_get.return_value = self._mock_doc()
        mock_text.return_value = self.RICH_TEXT

        result = compute_strictness_score(1)

        assert abs(result.bar_width_pct - result.score * 10) < 0.01

    @patch("apps.comparison.strictness._get_full_text")
    @patch("apps.library.models.Document.objects.get")
    def test_summary_line_format(self, mock_get, mock_text):
        mock_get.return_value = self._mock_doc()
        mock_text.return_value = self.RICH_TEXT

        result = compute_strictness_score(1)

        assert "mandatory verbs" in result.summary_line
        assert "numeric thresholds" in result.summary_line
        assert "penalties" in result.summary_line
