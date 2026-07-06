"""
insights.py — Insights tab generation (Tab 5).

Produces four cards:
  1. AI Summary         — LLM executive summary (3 sentences)
  2. Top 3 Divergences  — computed importance ranking
  3. BBK Implications   — LLM, grounded in retrieved BBK policy excerpts
  4. Confidence Dist.   — histogram buckets (no LLM)
"""
import json

from apps.comparison.models import ComparisonResult, REL_LABELS

# ── Importance weights ─────────────────────────────────────────────────────────

_REL_WEIGHT = {
    'conflicting':     1.0,
    'stricter_in_a':   0.7,
    'stricter_in_b':   0.7,
    'additional_in_a': 0.5,
    'additional_in_b': 0.5,
    'equivalent':      0.0,
}

_PRINCIPLE_CRITICALITY = {
    'breach':               1.0,
    'cross_border_transfer': 0.9,
    'data_subject':         0.8,
    'consent':              0.7,
    'processing_grounds':   0.6,
    'dpia':                 0.6,
    'vendor_processor':     0.5,
    'retention':            0.4,
    'adequacy':             0.5,
    'supervisory_authority':0.4,
    'data_controller':      0.3,
}

# ── Histogram bins ─────────────────────────────────────────────────────────────

_BINS = [
    (0.00, 0.15, '0–14%',   '#002583'),
    (0.15, 0.29, '15–28%',  '#002583'),
    (0.29, 0.43, '29–42%',  '#002583'),
    (0.43, 0.57, '43–56%',  '#FFB800'),
    (0.57, 0.71, '57–70%',  '#FFB800'),
    (0.71, 0.86, '71–85%',  '#FFB800'),
    (0.86, 1.01, '86–100%', '#FFB800'),
]


# ── Public API ─────────────────────────────────────────────────────────────────

def get_top_divergences(results, n: int = 3) -> list:
    scored = []
    for r in results:
        rw = _REL_WEIGHT.get(r.relationship, 0)
        if rw == 0:
            continue
        pc = max((_PRINCIPLE_CRITICALITY.get(p, 0.3) for p in (r.principle_ids or [])), default=0.3)
        importance = (
            0.40 * rw
            + 0.30 * r.confidence
            + 0.20 * (1 - r.similarity_score)
            + 0.10 * pc
        )
        scored.append((importance, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:n]]


def compute_confidence_histogram(results) -> list:
    counts = [0] * len(_BINS)
    for r in results:
        for i, (lo, hi, *_) in enumerate(_BINS):
            if lo <= r.confidence < hi:
                counts[i] += 1
                break

    max_count = max(counts, default=1) or 1
    return [
        {
            'label':      _BINS[i][2],
            'count':      counts[i],
            'height_pct': round(counts[i] / max_count * 100),
            'color':      _BINS[i][3],
            'lo':         _BINS[i][0],
            'hi':         _BINS[i][1],
        }
        for i in range(len(_BINS))
    ]


def generate_ai_summary(run) -> str:
    """Call the LLM to produce a 3-sentence executive summary. Returns plain text."""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from reasoning.llm_shims import _call_llm, _extract_json
    except Exception:
        return _fallback_summary(run)

    results = list(run.results.exclude(lifecycle=ComparisonResult.REJECTED)
                   .order_by('id')[:40])

    if not results:
        return f'No comparison results available yet for {run.pair_label}.'

    pairs_text = _serialize_pairs(results[:20])

    from apps.comparison.strictness import compute_strictness_score
    try:
        score_a = compute_strictness_score(run.reg_a_id)
        score_b = compute_strictness_score(run.reg_b_id)
        strictness_text = (
            f'- {run.reg_a.name}: {score_a.score}/10 ({score_a.score_tier})\n'
            f'- {run.reg_b.name}: {score_b.score}/10 ({score_b.score_tier})'
        )
    except Exception:
        strictness_text = '(strictness scores unavailable)'

    prompt = f"""\
You are analyzing a regulatory comparison for a compliance analyst at BBK (Bank of Bahrain and Kuwait).

Regulations compared:
- {run.reg_a.name} ({run.reg_a.get_jurisdiction_display()})
- {run.reg_b.name} ({run.reg_b.get_jurisdiction_display()})

Topics: {run.topics_display}

Key results:
{pairs_text}

Strictness:
{strictness_text}

Write a 3-sentence executive summary of what this comparison shows.

Rules:
1. Write in plain, non-legalistic English.
2. Lead with the single most important finding.
3. Mention the stricter jurisdiction if material.
4. Do NOT issue legal determinations. Use neutral language.
5. Do NOT invent facts not in the data.
6. Maximum 3 sentences, under 70 words total.

Return JSON: {{"summary": "..."}}"""

    try:
        raw = _call_llm(prompt, max_tokens=256)
        data = _extract_json(raw)
        return data.get('summary', _fallback_summary(run))
    except Exception:
        return _fallback_summary(run)


def generate_bbk_implications(run, top_divergences: list) -> str:
    """Generate BBK-specific implications. Returns plain text."""
    if not top_divergences:
        return 'No significant divergences identified in this comparison.'

    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from reasoning.llm_shims import _call_llm, _extract_json
    except Exception:
        return _fallback_implications(run, top_divergences)

    divs_text = '\n'.join(
        f'{i+1}. {r.citation_a} ↔ {r.citation_b or "—"}: '
        f'{REL_LABELS.get(r.relationship, r.relationship)} — {r.key_difference or r.rationale[:100]}'
        for i, r in enumerate(top_divergences)
    )

    prompt = f"""\
You are a compliance analyst at BBK (Bank of Bahrain and Kuwait).

Top divergences found in {run.reg_a.name} vs {run.reg_b.name}:
{divs_text}

Write 2 sentences describing what BBK needs to consider.
Rules:
1. Focus on actionable implications, not restating the divergences.
2. Use "may need to review" / "should consider" phrasing.
3. Never recommend specific legal actions.
4. Maximum 2 sentences.

Return JSON: {{"implications": "..."}}"""

    try:
        raw = _call_llm(prompt, max_tokens=200)
        data = _extract_json(raw)
        return data.get('implications', _fallback_implications(run, top_divergences))
    except Exception:
        return _fallback_implications(run, top_divergences)


# ── Fallbacks ──────────────────────────────────────────────────────────────────

def _serialize_pairs(results) -> str:
    lines = []
    for r in results:
        b = r.citation_b or '—'
        lines.append(
            f'- {r.citation_a} ↔ {b}: '
            f'{REL_LABELS.get(r.relationship, r.relationship)} '
            f'({r.confidence_pct}% confidence)'
            + (f' — {r.key_difference[:80]}' if r.key_difference else '')
        )
    return '\n'.join(lines)


def _fallback_summary(run) -> str:
    results = list(run.results.all())
    if not results:
        return f'Comparison of {run.pair_label} is complete but contains no pairs.'
    total = len(results)
    eq    = sum(1 for r in results if r.relationship == 'equivalent')
    conf  = sum(1 for r in results if r.relationship == 'conflicting')
    return (
        f'The comparison of {run.pair_label} analyzed {total} clause pairs across {run.topics_display}. '
        f'{eq} pairs were found equivalent, while {conf} showed conflicting provisions. '
        f'Review the Clauses tab for detailed analysis and lifecycle actions.'
    )


def _fallback_implications(run, top_divergences) -> str:
    if not top_divergences:
        return 'No material divergences requiring BBK attention were identified.'
    r = top_divergences[0]
    return (
        f'BBK should consider reviewing its policies related to '
        f'{r.citation_a} ↔ {r.citation_b or "—"} ({REL_LABELS.get(r.relationship, r.relationship)}), '
        f'as differences between {run.reg_a.name} and {run.reg_b.name} may affect operational compliance. '
        f'Legal review is recommended before any policy changes.'
    )
