"""
strictness.py — Jurisdictional Strictness Meter computation (Visual 9).

Produces a 0–10 strictness score from four objective textual signals:
  1. mandatory_verb_density  (weight 0.35)
  2. numeric_thresholds      (weight 0.25)
  3. penalty_severity        (weight 0.30)
  4. specificity_ratio       (weight 0.10)
"""
import re
import sqlite3
from dataclasses import dataclass
from typing import Any


# ── Regex patterns ─────────────────────────────────────────────────────────────

MANDATORY_VERB_PATTERN = re.compile(
    r'\b(shall|must|is required to|are required to|may not|shall not|must not|'
    r'is obligated to|are obligated to|has a duty to|have a duty to)\b',
    re.IGNORECASE,
)

NUMERIC_THRESHOLD_PATTERN = re.compile(
    r'\b(\d+)\s*(hours?|days?|months?|years?|%|percent|BHD|KWD|INR|'
    r'thousand|million|working days?)(?=\W|$)',
    re.IGNORECASE,
)

PENALTY_KEYWORDS = {
    "severe":   ["imprisonment", "criminal liability", "revocation of license"],
    "moderate": ["fine not exceeding", "administrative penalty", "suspension"],
    "minor":    ["warning", "notice of violation", "corrective action"],
}

PENALTY_NORMALIZED = {"none": 0.0, "minor": 0.33, "moderate": 0.66, "severe": 1.0}

TIER_BAR_COLOR = {
    "lenient":  "#E5E8EF",
    "moderate": "#FFB800",
    "strict":   "#FFB800",
    "severe":   "#002583",
}

COMPONENT_LABELS = {
    "mandatory_verb_density": "Mandatory verb density",
    "numeric_thresholds":     "Numeric thresholds",
    "penalty_severity":       "Penalty severity",
    "specificity_ratio":      "Specificity ratio",
}


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ComponentDetail:
    value: Any
    normalized: float
    weight: float
    contribution: float
    label: str = ""


@dataclass
class StrictnessResult:
    document_id: int
    document_name: str
    score: float
    score_tier: str
    bar_color: str
    bar_width_pct: float
    components: dict
    summary_line: str


# ── Private helpers ────────────────────────────────────────────────────────────

def _get_full_text(doc) -> str:
    """Retrieve all chunk text for a document from the BM25 SQLite FTS5 store."""
    try:
        from config import CHROMA_DIR
        db_path = CHROMA_DIR / "bm25.db"
    except Exception:
        return ""
    if not db_path.exists():
        return ""
    title = doc.full_name or doc.name
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT content FROM bm25_index WHERE doc_title = ?",
            (title,),
        ).fetchall()
        conn.close()
        return " ".join(r[0] for r in rows if r[0])
    except sqlite3.OperationalError:
        return ""


def _classify_penalty_language(text: str) -> str:
    text_lower = text.lower()
    for tier in ("severe", "moderate", "minor"):
        for kw in PENALTY_KEYWORDS[tier]:
            if kw in text_lower:
                return tier
    return "none"


def _compute_specificity(text: str) -> float:
    """Fraction of sentences containing at least one mandatory verb."""
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if not sentences:
        return 0.0
    specific = sum(1 for s in sentences if MANDATORY_VERB_PATTERN.search(s))
    return specific / len(sentences)


def _score_tier(score: float) -> str:
    if score >= 8.5:
        return "severe"
    if score >= 7.0:
        return "strict"
    if score >= 4.0:
        return "moderate"
    return "lenient"


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_strictness_score(document_id: int) -> StrictnessResult:
    from apps.library.models import Document

    doc = Document.objects.get(pk=document_id)
    text = _get_full_text(doc)

    if not text.strip():
        return StrictnessResult(
            document_id=document_id,
            document_name=doc.name,
            score=0.0,
            score_tier="lenient",
            bar_color=TIER_BAR_COLOR["lenient"],
            bar_width_pct=0.0,
            components={},
            summary_line="No text analyzed yet",
        )

    # Component 1: mandatory verb density (per 1000 words)
    mandatory_count = len(MANDATORY_VERB_PATTERN.findall(text))
    word_count = max(len(text.split()), 1)
    verb_density = (mandatory_count / word_count) * 1000
    verb_normalized = min(verb_density / 40, 1.0)

    # Component 2: numeric thresholds
    numeric_count = len(NUMERIC_THRESHOLD_PATTERN.findall(text))
    numeric_normalized = min(numeric_count / 20, 1.0)

    # Component 3: penalty severity
    penalty_tier = _classify_penalty_language(text)
    penalty_normalized = PENALTY_NORMALIZED[penalty_tier]

    # Component 4: specificity ratio
    specificity = _compute_specificity(text)

    weights = {"verb": 0.35, "numeric": 0.25, "penalty": 0.30, "specificity": 0.10}

    score = (
        verb_normalized   * weights["verb"] +
        numeric_normalized * weights["numeric"] +
        penalty_normalized * weights["penalty"] +
        specificity        * weights["specificity"]
    ) * 10
    score = round(score, 1)
    tier = _score_tier(score)

    components = {
        "mandatory_verb_density": ComponentDetail(
            value=mandatory_count,
            normalized=round(verb_normalized, 2),
            weight=weights["verb"],
            contribution=round(verb_normalized * weights["verb"], 2),
            label=COMPONENT_LABELS["mandatory_verb_density"],
        ),
        "numeric_thresholds": ComponentDetail(
            value=numeric_count,
            normalized=round(numeric_normalized, 2),
            weight=weights["numeric"],
            contribution=round(numeric_normalized * weights["numeric"], 2),
            label=COMPONENT_LABELS["numeric_thresholds"],
        ),
        "penalty_severity": ComponentDetail(
            value=penalty_tier,
            normalized=round(penalty_normalized, 2),
            weight=weights["penalty"],
            contribution=round(penalty_normalized * weights["penalty"], 2),
            label=COMPONENT_LABELS["penalty_severity"],
        ),
        "specificity_ratio": ComponentDetail(
            value=round(specificity, 2),
            normalized=round(specificity, 2),
            weight=weights["specificity"],
            contribution=round(specificity * weights["specificity"], 2),
            label=COMPONENT_LABELS["specificity_ratio"],
        ),
    }

    summary_line = (
        f"{mandatory_count} mandatory verbs · "
        f"{numeric_count} numeric thresholds · "
        f"{penalty_tier} penalties"
    )

    return StrictnessResult(
        document_id=document_id,
        document_name=doc.name,
        score=score,
        score_tier=tier,
        bar_color=TIER_BAR_COLOR[tier],
        bar_width_pct=round(score * 10, 1),
        components=components,
        summary_line=summary_line,
    )
