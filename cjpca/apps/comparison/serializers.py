"""
serializers.py — Arc data serializer for the equivalency arc diagram.
Supports both V1 (ClausePair) and V2 (ComparisonResult) models.
"""
import hashlib

from apps.comparison.models import (
    ClausePair, ComparisonResult,
    REL_COLORS, REL_LABELS,
)

# ── SVG layout constants ────────────────────────────────────────────────────────

LEFT_BOX_X  = 40
RIGHT_BOX_X = 480
BOX_W       = 120
BOX_H       = 22
ARC_LEFT_X  = 160
ARC_RIGHT_X = 480
ARC_MID_X   = 320
ROW_STEP    = 32
TOP_OFFSET  = 20
SVG_MIN_H   = 360

DASH = {'high': '', 'medium': '5 3', 'low': '2 3'}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _article_id(side: str, label: str) -> str:
    h = hashlib.md5(label.encode()).hexdigest()[:8]
    return f'{side}_{h}'


def _confidence_tier(confidence: float) -> str:
    if confidence >= 0.85:
        return 'high'
    if confidence >= 0.70:
        return 'medium'
    return 'low'


def _stroke_width(tier: str, sim: float) -> float:
    if tier == 'high':
        return round(1.5 + sim * 2, 2)
    if tier == 'medium':
        return round(1.2 + sim * 1.5, 2)
    return round(1.0 + sim * 1.0, 2)


def _arc_center_y(y_position: int, offset: int = 0) -> int:
    return 31 + y_position * ROW_STEP + offset


def _box_y(y_position: int) -> int:
    return TOP_OFFSET + y_position * ROW_STEP


def _path_d(left_y: int, right_y: int) -> str:
    return (
        f'M {ARC_LEFT_X} {left_y} '
        f'C {ARC_MID_X} {left_y}, {ARC_MID_X} {right_y}, {ARC_RIGHT_X} {right_y}'
    )


def _build_arc_payload(
    reg_a_name: str,
    reg_b_name: str,
    reg_a_id: str,
    reg_b_id: str,
    pairs: list,  # list of (citation_a, citation_b, relationship, confidence, similarity, pk)
) -> dict:
    a_labels, b_labels = [], []
    a_seen, b_seen = set(), set()

    for citation_a, citation_b, *_ in pairs:
        if citation_a and citation_a not in a_seen:
            a_labels.append(citation_a)
            a_seen.add(citation_a)
        if citation_b and citation_b not in b_seen:
            b_labels.append(citation_b)
            b_seen.add(citation_b)

    a_pos = {lbl: i for i, lbl in enumerate(a_labels)}
    b_pos = {lbl: i for i, lbl in enumerate(b_labels)}

    arcs = []
    overlap_tracker = {}

    for citation_a, citation_b, relationship, confidence, similarity, pk in pairs:
        if not citation_b:
            continue

        src_id = _article_id('a', citation_a)
        tgt_id = _article_id('b', citation_b)
        tier   = _confidence_tier(confidence)
        key    = (src_id, tgt_id)
        offset = overlap_tracker.get(key, 0) * 4
        overlap_tracker[key] = overlap_tracker.get(key, 0) + 1

        src_y  = a_pos.get(citation_a, 0)
        tgt_y  = b_pos.get(citation_b, 0)
        left_y = _arc_center_y(src_y)
        right_y = _arc_center_y(tgt_y, offset)
        sw     = _stroke_width(tier, similarity)

        tooltip = (
            f'{citation_a} \u2194 {citation_b} \u00b7 '
            f'{REL_LABELS.get(relationship, relationship)} \u00b7 '
            f'{round(confidence * 100)}% confidence'
        )

        arcs.append({
            'id':                src_id + '__' + tgt_id + f'_{pk}',
            'pair_pk':           pk,
            'source_article_id': src_id,
            'target_article_id': tgt_id,
            'source_citation':   citation_a,
            'target_citation':   citation_b or '',
            'relationship':      relationship,
            'similarity_score':  round(similarity, 2),
            'confidence':        round(confidence, 2),
            'confidence_tier':   tier,
            'tooltip':           tooltip,
            'stroke_color':      REL_COLORS.get(relationship, '#D1D5E0'),
            'stroke_width':      sw,
            'stroke_dasharray':  DASH[tier],
            'path_d':            _path_d(left_y, right_y),
            'left_y':            left_y,
            'right_y':           right_y,
        })

    total_arcs = len(arcs)
    capped     = total_arcs > 100
    if capped:
        arcs = sorted(arcs, key=lambda a: a['confidence'], reverse=True)[:100]

    max_articles = max(len(a_labels), len(b_labels), 1)
    svg_h        = max(SVG_MIN_H, _box_y(max_articles) + 20)
    scrollable   = svg_h > SVG_MIN_H

    def _short(lbl):
        """Extract article/section number from a full citation string."""
        if '—' in lbl:
            return lbl.split('—', 1)[1].strip()
        if '\u2014' in lbl:
            return lbl.split('\u2014', 1)[1].strip()
        return lbl

    def _make_articles(labels):
        return [
            {
                'id':          _article_id('a' if labels is a_labels else 'b', lbl),
                'label':       lbl,
                'short_label': _short(lbl),
                'y_position':  i,
                'box_y':       _box_y(i),
                'text_y':      _box_y(i) + 15,
                'center_y':    _arc_center_y(i),
            }
            for i, lbl in enumerate(labels)
        ]

    return {
        'regulation_a': {'id': reg_a_id, 'name': reg_a_name, 'articles': _make_articles(a_labels)},
        'regulation_b': {'id': reg_b_id, 'name': reg_b_name, 'articles': _make_articles(b_labels)},
        'arcs':         arcs,
        'total_arcs':   total_arcs,
        'capped':       capped,
        'svg_height':   svg_h,
        'scrollable':   scrollable,
    }


# ── V1 serializer (kept for /v1/ workspace backward compat) ────────────────────

class ArcDataSerializer:
    """Serializes a V1 ComparisonAnalysis into arc diagram data."""

    def __init__(self, analysis):
        self.analysis = analysis

    def serialize(self) -> dict:
        pairs_qs = self.analysis.clause_pairs.all().order_by('id')
        pairs = []
        for p in pairs_qs:
            relationship = self._map_v1_relationship(p)
            confidence   = p.similarity_score / 100.0
            similarity   = p.similarity_score / 100.0
            pairs.append((p.reg_a_article, p.reg_b_article, relationship, confidence, similarity, p.pk))

        return _build_arc_payload(
            reg_a_name=self.analysis.reg_a.name,
            reg_b_name=self.analysis.reg_b.name,
            reg_a_id=str(self.analysis.reg_a.pk),
            reg_b_id=str(self.analysis.reg_b.pk),
            pairs=pairs,
        )

    @staticmethod
    def _map_v1_relationship(pair: ClausePair) -> str:
        import json as _json
        if not pair.reg_b_article:
            return 'additional_in_a'
        if pair.match_type == ClausePair.EQUIVALENT:
            return 'equivalent'
        if pair.match_type == ClausePair.PARTIAL:
            try:
                ai = _json.loads(pair.ai_analysis) if pair.ai_analysis else {}
            except Exception:
                ai = {}
            sj = ai.get('stricter_jurisdiction', '').lower()
            if 'a' in sj and 'b' not in sj:
                return 'stricter_in_a'
            if 'b' in sj and 'a' not in sj:
                return 'stricter_in_b'
            return 'equivalent'
        if pair.match_type == ClausePair.SIMILAR:
            return 'conflicting'
        return 'additional_in_b'


# ── V2 serializer ──────────────────────────────────────────────────────────────

class RunArcSerializer:
    """Serializes a V2 ComparisonRun into arc diagram data."""

    def __init__(self, run):
        self.run = run

    def serialize(self) -> dict:
        results_qs = self.run.results.all().order_by('id')
        pairs = [
            (r.citation_a, r.citation_b, r.relationship, r.confidence, r.similarity_score, r.pk)
            for r in results_qs
        ]
        return _build_arc_payload(
            reg_a_name=self.run.reg_a.name,
            reg_b_name=self.run.reg_b.name,
            reg_a_id=str(self.run.reg_a.pk),
            reg_b_id=str(self.run.reg_b.pk),
            pairs=pairs,
        )
