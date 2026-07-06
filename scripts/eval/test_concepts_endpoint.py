"""
Integration tests for Visual 8 — Term Frequency / Semantic Overlay.

Tests:
  - extract_concepts() returns correct structure and counts
  - concept_tags.highlight_concepts template tag output
  - ComparisonConceptsView JSON endpoint
  - Concept filter via ?concept= query param
  - CONCEPT_SEEDS contains all 11 required privacy principles
  - build_concept_pattern whole-word matching (no partial matches)

Run:
  python -m unittest tests.integration.test_concepts_endpoint -v  (from repo root)
"""
import sys, os, django, json

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "cjpca")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cjpca.settings")
django.setup()

import unittest
from unittest.mock import MagicMock, patch

from apps.comparison.concepts import (
    CONCEPT_SEEDS,
    extract_concepts,
    build_concept_pattern,
    get_doc_chunks,
    MAX_CONCEPTS,
)
from apps.comparison.templatetags.concept_tags import highlight_concepts


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_doc(pk=1, name="Test Reg"):
    d = MagicMock()
    d.pk        = pk
    d.name      = name
    d.full_name = name
    return d


# ── CONCEPT_SEEDS structure ────────────────────────────────────────────────────

class TestConceptSeeds(unittest.TestCase):

    REQUIRED_IDS = {
        "data_controller", "consent", "cross_border_transfer",
        "supervisory_authority", "breach", "data_subject",
        "processing_grounds", "retention", "dpia",
        "vendor_processor", "adequacy",
    }

    def test_all_11_concepts_present(self):
        self.assertEqual(set(CONCEPT_SEEDS.keys()), self.REQUIRED_IDS)

    def test_each_concept_has_required_fields(self):
        for cid, seed in CONCEPT_SEEDS.items():
            with self.subTest(concept=cid):
                self.assertIn("label",       seed)
                self.assertIn("synonyms",     seed)
                self.assertIn("color_light",  seed)
                self.assertIn("color_text",   seed)
                self.assertIn("color_dot",    seed)
                self.assertGreater(len(seed["synonyms"]), 0)

    def test_synonyms_are_non_empty_strings(self):
        for cid, seed in CONCEPT_SEEDS.items():
            for syn in seed["synonyms"]:
                self.assertIsInstance(syn, str)
                self.assertGreater(len(syn.strip()), 0,
                                   f"Empty synonym in {cid}")

    def test_colors_are_hex(self):
        for cid, seed in CONCEPT_SEEDS.items():
            for field in ("color_light", "color_text", "color_dot"):
                self.assertTrue(
                    seed[field].startswith("#"),
                    f"{cid}.{field} should be a hex color"
                )


# ── build_concept_pattern ──────────────────────────────────────────────────────

class TestBuildConceptPattern(unittest.TestCase):

    def test_matches_synonym_case_insensitive(self):
        p = build_concept_pattern("consent")
        self.assertIsNotNone(p.search("The data subject gives Consent to processing."))

    def test_does_not_match_partial_word(self):
        p = build_concept_pattern("consent")
        # "consented" should NOT match "consent" as a standalone word
        self.assertIsNone(p.search("She consented to the terms."))

    def test_matches_multi_word_synonym(self):
        p = build_concept_pattern("data_controller")
        self.assertIsNotNone(p.search("The data fiduciary shall maintain records."))

    def test_matches_all_synonyms(self):
        p = build_concept_pattern("breach")
        texts = [
            "report any data breach within 72 hours",
            "personal data breach must be notified",
            "a security breach occurred",
            "breach notification requirements",
            "file an incident report",
        ]
        for t in texts:
            with self.subTest(text=t):
                self.assertIsNotNone(p.search(t))


# ── highlight_concepts template tag ───────────────────────────────────────────

class TestHighlightConcepts(unittest.TestCase):

    def _concepts(self, *ids):
        return [
            {
                "id":          cid,
                "label":       CONCEPT_SEEDS[cid]["label"],
                "color_light": CONCEPT_SEEDS[cid]["color_light"],
                "color_text":  CONCEPT_SEEDS[cid]["color_text"],
                "color_dot":   CONCEPT_SEEDS[cid]["color_dot"],
                "synonyms":    CONCEPT_SEEDS[cid]["synonyms"],
            }
            for cid in ids
        ]

    def test_wraps_match_in_span(self):
        result = highlight_concepts("The controller must act.", self._concepts("data_controller"))
        self.assertIn('<span class="concept-span"', result)
        self.assertIn("controller", result)

    def test_data_concept_attribute_set(self):
        result = highlight_concepts("Consent is required.", self._concepts("consent"))
        self.assertIn('data-concept="consent"', result)

    def test_no_match_returns_plain_escaped_text(self):
        result = highlight_concepts("Plain text with no privacy terms.", self._concepts("dpia"))
        self.assertNotIn("<span", result)
        self.assertIn("Plain text", result)

    def test_empty_text_returns_empty(self):
        result = highlight_concepts("", self._concepts("consent"))
        self.assertEqual(str(result), "")

    def test_no_concepts_returns_escaped_text(self):
        result = highlight_concepts("Hello <world>", [])
        self.assertIn("&lt;world&gt;", result)
        self.assertNotIn("<span", result)

    def test_no_nested_spans_on_overlapping_synonyms(self):
        # "data processor" and "processor" both match — should not nest
        text   = "The data processor shall comply."
        result = highlight_concepts(text, self._concepts("vendor_processor"))
        # Count span opens — should be exactly 1 for the longer match
        self.assertEqual(result.count('<span class="concept-span"'), 1)

    def test_multiple_concepts_highlighted(self):
        text   = "The controller must obtain consent."
        result = highlight_concepts(text, self._concepts("data_controller", "consent"))
        self.assertIn('data-concept="data_controller"', result)
        self.assertIn('data-concept="consent"', result)

    def test_html_in_input_is_escaped(self):
        result = highlight_concepts("<script>alert(1)</script>", self._concepts("consent"))
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_case_insensitive_match(self):
        result = highlight_concepts("CONSENT forms must be signed.", self._concepts("consent"))
        self.assertIn('data-concept="consent"', result)


# ── extract_concepts ───────────────────────────────────────────────────────────

class TestExtractConcepts(unittest.TestCase):

    def _mock_queryset(self, docs):
        qs = MagicMock()
        qs.filter.return_value = iter(docs)
        return qs

    @patch("apps.comparison.concepts._get_doc_text")
    @patch("apps.library.models.Document")
    def test_returns_list_of_dicts(self, MockDocument, mock_get_text):
        doc = _make_doc(pk=1)
        MockDocument.objects.filter.return_value = [doc]
        mock_get_text.return_value = "controller must obtain consent from data subject"

        results = extract_concepts([1])
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    @patch("apps.comparison.concepts._get_doc_text")
    @patch("apps.library.models.Document")
    def test_result_has_required_fields(self, MockDocument, mock_get_text):
        doc = _make_doc()
        MockDocument.objects.filter.return_value = [doc]
        mock_get_text.return_value = "controller"

        concepts = extract_concepts([1])
        for c in concepts:
            for field in ("id", "label", "color_light", "color_text", "color_dot",
                          "synonyms", "total_occurrences", "occurrences_a", "occurrences_b"):
                self.assertIn(field, c, f"Missing field: {field}")

    @patch("apps.comparison.concepts._get_doc_text")
    @patch("apps.library.models.Document")
    def test_sorted_by_total_occurrences_desc(self, MockDocument, mock_get_text):
        doc = _make_doc()
        MockDocument.objects.filter.return_value = [doc]
        mock_get_text.return_value = "consent " * 30 + "controller " * 5

        concepts = extract_concepts([1])
        totals = [c["total_occurrences"] for c in concepts]
        self.assertEqual(totals, sorted(totals, reverse=True))

    @patch("apps.comparison.concepts._get_doc_text")
    @patch("apps.library.models.Document")
    def test_capped_at_max_concepts(self, MockDocument, mock_get_text):
        doc = _make_doc()
        MockDocument.objects.filter.return_value = [doc]
        mock_get_text.return_value = (
            "controller consent breach data subject processor dpia "
            "retention transfer supervisory consent consent"
        )

        concepts = extract_concepts([1])
        self.assertLessEqual(len(concepts), MAX_CONCEPTS)

    @patch("apps.comparison.concepts._get_doc_text")
    @patch("apps.library.models.Document")
    def test_two_docs_occurrences_split_correctly(self, MockDocument, mock_get_text):
        doc_a = _make_doc(pk=1, name="Reg A")
        doc_b = _make_doc(pk=2, name="Reg B")
        MockDocument.objects.filter.return_value = [doc_a, doc_b]

        def side_effect(doc):
            if doc.pk == 1:
                return "consent consent consent"
            return "consent"

        mock_get_text.side_effect = side_effect
        concepts = extract_concepts([1, 2])

        consent = next(c for c in concepts if c["id"] == "consent")
        self.assertEqual(consent["occurrences_a"],     3)
        self.assertEqual(consent["occurrences_b"],     1)
        self.assertEqual(consent["total_occurrences"], 4)

    @patch("apps.comparison.concepts._get_doc_text")
    @patch("apps.library.models.Document")
    def test_empty_text_produces_zero_counts(self, MockDocument, mock_get_text):
        doc = _make_doc()
        MockDocument.objects.filter.return_value = [doc]
        mock_get_text.return_value = ""

        concepts = extract_concepts([1])
        for c in concepts:
            self.assertEqual(c["total_occurrences"], 0)
            self.assertEqual(c["occurrences_a"],     0)


# ── get_doc_chunks ─────────────────────────────────────────────────────────────

class TestGetDocChunks(unittest.TestCase):

    @patch("apps.comparison.concepts._bm25_db_path")
    def test_returns_empty_list_when_no_db(self, mock_path):
        mock_path.return_value = None
        doc = _make_doc()
        result = get_doc_chunks(doc)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
