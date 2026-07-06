"""
Unit tests for apps/comparison/serializers.py — Visual 6 Equivalency Confidence Arc.
Run: python -m pytest tests/unit/test_arc_serializer.py -v  (from repo root)
"""
import sys
import os
import django
import json

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "cjpca")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cjpca.settings")
django.setup()

import unittest
from unittest.mock import MagicMock, patch

from apps.comparison.serializers import (
    ArcDataSerializer,
    _article_id,
    _confidence_tier,
    _stroke_width,
    _map_relationship,
    _arc_center_y,
    _box_y,
    _path_d,
    REL_COLORS,
    DASH,
)
from apps.comparison.models import ClausePair


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_pair(pk=1, reg_a="Art. 1", reg_b="Art. 2",
               match_type="equivalent", score=95.0, ai_json=None):
    p = MagicMock(spec=ClausePair)
    p.pk = pk
    p.reg_a_article = reg_a
    p.reg_b_article = reg_b
    p.match_type = match_type
    p.similarity_score = score
    p.ai_analysis = json.dumps(ai_json) if ai_json else ""
    return p


def _make_analysis(pairs, reg_a_name="Reg A", reg_b_name="Reg B"):
    reg_a = MagicMock(); reg_a.pk = 1; reg_a.name = reg_a_name
    reg_b = MagicMock(); reg_b.pk = 2; reg_b.name = reg_b_name
    analysis = MagicMock()
    analysis.reg_a = reg_a
    analysis.reg_b = reg_b
    analysis.clause_pairs.all.return_value.order_by.return_value = pairs
    return analysis


# ── Unit helpers ───────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_article_id_stable(self):
        id1 = _article_id("a", "Art. 3")
        id2 = _article_id("a", "Art. 3")
        self.assertEqual(id1, id2)

    def test_article_id_differs_by_side(self):
        self.assertNotEqual(_article_id("a", "Art. 3"), _article_id("b", "Art. 3"))

    def test_article_id_differs_by_label(self):
        self.assertNotEqual(_article_id("a", "Art. 3"), _article_id("a", "Art. 4"))

    def test_confidence_tier_high(self):
        self.assertEqual(_confidence_tier(0.85), "high")
        self.assertEqual(_confidence_tier(0.95), "high")
        self.assertEqual(_confidence_tier(1.0), "high")

    def test_confidence_tier_medium(self):
        self.assertEqual(_confidence_tier(0.70), "medium")
        self.assertEqual(_confidence_tier(0.80), "medium")
        self.assertEqual(_confidence_tier(0.849), "medium")

    def test_confidence_tier_low(self):
        self.assertEqual(_confidence_tier(0.0), "low")
        self.assertEqual(_confidence_tier(0.5), "low")
        self.assertEqual(_confidence_tier(0.699), "low")

    def test_stroke_width_high(self):
        sw = _stroke_width("high", 1.0)
        self.assertAlmostEqual(sw, 3.5)
        sw_min = _stroke_width("high", 0.0)
        self.assertAlmostEqual(sw_min, 1.5)

    def test_stroke_width_medium(self):
        sw = _stroke_width("medium", 0.0)
        self.assertAlmostEqual(sw, 1.2)

    def test_stroke_width_low(self):
        sw = _stroke_width("low", 0.0)
        self.assertAlmostEqual(sw, 1.0)

    def test_arc_center_y_formula(self):
        self.assertEqual(_arc_center_y(0), 31)
        self.assertEqual(_arc_center_y(1), 63)
        self.assertEqual(_arc_center_y(2), 95)

    def test_arc_center_y_offset(self):
        self.assertEqual(_arc_center_y(0, 4), 35)

    def test_box_y_formula(self):
        self.assertEqual(_box_y(0), 20)
        self.assertEqual(_box_y(1), 52)

    def test_path_d_format(self):
        d = _path_d(31, 63)
        self.assertIn("M 160 31", d)
        self.assertIn("C 320 31", d)
        self.assertIn("320 63", d)
        self.assertIn("480 63", d)


# ── Relationship mapping ───────────────────────────────────────────────────────

class TestMapRelationship(unittest.TestCase):

    def test_equivalent(self):
        p = _make_pair(match_type="equivalent")
        self.assertEqual(_map_relationship(p), "equivalent")

    def test_no_reg_b_is_additional_in_a(self):
        p = _make_pair(reg_b="", match_type="none", score=5.0)
        self.assertEqual(_map_relationship(p), "additional_in_a")

    def test_partial_stricter_a(self):
        p = _make_pair(match_type="partial",
                       ai_json={"stricter_jurisdiction": "Reg A"})
        self.assertEqual(_map_relationship(p), "stricter_in_a")

    def test_partial_stricter_b(self):
        p = _make_pair(match_type="partial",
                       ai_json={"stricter_jurisdiction": "Reg B"})
        self.assertEqual(_map_relationship(p), "stricter_in_b")

    def test_partial_no_stricter(self):
        p = _make_pair(match_type="partial",
                       ai_json={"stricter_jurisdiction": "Neither"})
        self.assertEqual(_map_relationship(p), "equivalent")

    def test_similar_is_conflicting(self):
        p = _make_pair(match_type="similar", score=35.0)
        self.assertEqual(_map_relationship(p), "conflicting")

    def test_none_with_reg_b_is_additional_in_b(self):
        p = _make_pair(match_type="none", score=5.0)
        # reg_b is set (default "Art. 2")
        self.assertEqual(_map_relationship(p), "additional_in_b")

    def test_invalid_ai_json_falls_back_gracefully(self):
        p = _make_pair(match_type="partial")
        p.ai_analysis = "NOT JSON"
        result = _map_relationship(p)
        self.assertIn(result, ("equivalent", "stricter_in_a", "stricter_in_b"))


# ── ArcDataSerializer ──────────────────────────────────────────────────────────

class TestArcDataSerializer(unittest.TestCase):

    def test_data_contract_shape(self):
        pairs = [_make_pair(pk=1)]
        analysis = _make_analysis(pairs)
        data = ArcDataSerializer(analysis).serialize()

        self.assertIn("regulation_a", data)
        self.assertIn("regulation_b", data)
        self.assertIn("arcs", data)
        self.assertIn("total_arcs", data)
        self.assertIn("capped", data)
        self.assertIn("svg_height", data)
        self.assertIn("scrollable", data)

    def test_regulation_fields(self):
        pairs = [_make_pair()]
        analysis = _make_analysis(pairs, "Bahrain PDPL", "Kuwait DPPR")
        data = ArcDataSerializer(analysis).serialize()

        self.assertEqual(data["regulation_a"]["name"], "Bahrain PDPL")
        self.assertEqual(data["regulation_b"]["name"], "Kuwait DPPR")

    def test_article_y_positions_ordered(self):
        pairs = [
            _make_pair(pk=1, reg_a="Art. 1", reg_b="Art. A"),
            _make_pair(pk=2, reg_a="Art. 2", reg_b="Art. B"),
            _make_pair(pk=3, reg_a="Art. 3", reg_b="Art. C"),
        ]
        analysis = _make_analysis(pairs)
        data = ArcDataSerializer(analysis).serialize()

        a_arts = data["regulation_a"]["articles"]
        self.assertEqual(a_arts[0]["label"], "Art. 1")
        self.assertEqual(a_arts[0]["y_position"], 0)
        self.assertEqual(a_arts[1]["y_position"], 1)
        self.assertEqual(a_arts[2]["y_position"], 2)

    def test_article_svg_coords_computed(self):
        pairs = [_make_pair(pk=1, reg_a="Art. 1", reg_b="Art. A")]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        art = data["regulation_a"]["articles"][0]

        self.assertIn("box_y", art)
        self.assertIn("text_y", art)
        self.assertIn("center_y", art)
        self.assertEqual(art["box_y"], 20)       # 20 + 0*32
        self.assertEqual(art["center_y"], 31)    # 31 + 0*32

    def test_arc_has_all_required_fields(self):
        pairs = [_make_pair(pk=7)]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        arc = data["arcs"][0]

        for field in ("id", "source_article_id", "target_article_id", "relationship",
                      "similarity_score", "confidence", "confidence_tier", "tooltip",
                      "stroke_color", "stroke_width", "stroke_dasharray", "path_d"):
            self.assertIn(field, arc, f"Missing field: {field}")

    def test_all_six_relationships_map_to_valid_color(self):
        valid_rels = set(REL_COLORS.keys())
        pairs = [
            _make_pair(pk=1, match_type="equivalent", score=95),
            _make_pair(pk=2, match_type="partial", score=65,
                       ai_json={"stricter_jurisdiction": "a"}),
            _make_pair(pk=3, match_type="partial", score=65,
                       ai_json={"stricter_jurisdiction": "b"}),
            _make_pair(pk=4, match_type="similar", score=35),
            _make_pair(pk=5, reg_b="", match_type="none", score=5),
            _make_pair(pk=6, match_type="none", score=5),
        ]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        for arc in data["arcs"]:
            self.assertIn(arc["relationship"], valid_rels)
            self.assertIn(arc["stroke_color"], REL_COLORS.values())

    def test_three_confidence_tiers_produce_correct_dasharray(self):
        # equivalent → 95% → high (solid)
        # similar → 35% → low ("2 3")
        pairs = [
            _make_pair(pk=1, match_type="equivalent", score=95),
            _make_pair(pk=2, match_type="similar", score=35),
        ]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        arcs_by_pair = {a["pair_pk"]: a for a in data["arcs"]}

        self.assertEqual(arcs_by_pair[1]["confidence_tier"], "high")
        self.assertEqual(arcs_by_pair[1]["stroke_dasharray"], "")
        self.assertEqual(arcs_by_pair[2]["confidence_tier"], "low")
        self.assertEqual(arcs_by_pair[2]["stroke_dasharray"], "2 3")

    def test_tooltip_format(self):
        pairs = [_make_pair(pk=1, reg_a="PDPL Art. 3", reg_b="DPPR Art. 2",
                            match_type="equivalent", score=95)]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        tooltip = data["arcs"][0]["tooltip"]

        self.assertIn("PDPL Art. 3", tooltip)
        self.assertIn("DPPR Art. 2", tooltip)
        self.assertIn("95%", tooltip)

    def test_additional_in_a_not_in_arcs(self):
        pairs = [_make_pair(pk=1, reg_b="", match_type="none", score=5)]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        self.assertEqual(len(data["arcs"]), 0)

    def test_overlap_offset_applied(self):
        # Two pairs with the same source and target → second gets 4px offset
        pairs = [
            _make_pair(pk=1, reg_a="Art. X", reg_b="Art. Y", score=95),
            _make_pair(pk=2, reg_a="Art. X", reg_b="Art. Y", score=65),
        ]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        self.assertEqual(len(data["arcs"]), 2)
        right_ys = [a["right_y"] for a in data["arcs"]]
        self.assertNotEqual(right_ys[0], right_ys[1])
        self.assertEqual(right_ys[1], right_ys[0] + 4)

    def test_caps_at_100_arcs(self):
        pairs = [
            _make_pair(pk=i, reg_a=f"Art. {i}", reg_b=f"Cls. {i}", score=50)
            for i in range(120)
        ]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        self.assertEqual(len(data["arcs"]), 100)
        self.assertEqual(data["total_arcs"], 120)
        self.assertTrue(data["capped"])

    def test_under_100_arcs_not_capped(self):
        pairs = [_make_pair(pk=i, reg_a=f"Art. {i}", reg_b=f"Cls. {i}") for i in range(5)]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        self.assertFalse(data["capped"])
        self.assertEqual(data["total_arcs"], 5)

    def test_svg_height_min_360(self):
        pairs = [_make_pair(pk=1)]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        self.assertGreaterEqual(data["svg_height"], 360)

    def test_svg_height_grows_for_many_articles(self):
        pairs = [
            _make_pair(pk=i, reg_a=f"Art. {i}", reg_b=f"Cls. {i}")
            for i in range(20)
        ]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        self.assertGreater(data["svg_height"], 360)
        self.assertTrue(data["scrollable"])

    def test_empty_pairs_produces_empty_arcs(self):
        data = ArcDataSerializer(_make_analysis([])).serialize()
        self.assertEqual(data["arcs"], [])
        self.assertEqual(data["total_arcs"], 0)
        self.assertFalse(data["capped"])

    def test_unique_articles_deduplicated(self):
        # Same reg_a_article in two pairs → only one article box
        pairs = [
            _make_pair(pk=1, reg_a="Art. 1", reg_b="Art. A"),
            _make_pair(pk=2, reg_a="Art. 1", reg_b="Art. B"),
        ]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        a_labels = [a["label"] for a in data["regulation_a"]["articles"]]
        self.assertEqual(a_labels.count("Art. 1"), 1)

    def test_path_d_uses_correct_x_coords(self):
        pairs = [_make_pair(pk=1)]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        d = data["arcs"][0]["path_d"]
        self.assertIn("M 160", d)
        self.assertIn("480", d)
        self.assertIn("320", d)

    def test_similarity_score_normalised_to_0_1(self):
        pairs = [_make_pair(pk=1, score=95.0)]
        data = ArcDataSerializer(_make_analysis(pairs)).serialize()
        arc = data["arcs"][0]
        self.assertAlmostEqual(arc["similarity_score"], 0.95)
        self.assertAlmostEqual(arc["confidence"], 0.95)


if __name__ == "__main__":
    unittest.main()
