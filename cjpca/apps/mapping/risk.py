"""Multi-factor risk scoring for compliance gaps.

Replaces the flat severity classifier (`derive_severity`) with a transparent,
auditable score combining three weighted factors:

    risk_score = penalty_weight * enforcement_weight * impact_weight * coverage_factor

Each factor is in [0, 1]; the product is in [0, 1] and is then bucketed into
Critical / High / Medium / Low for UI display. The weights are kept in this
module so the formula is reviewable in code review (no hidden config tables).

The factors:
  - penalty_weight   : how big the worst-case fine/criminal penalty is in the
                       cited jurisdiction. Bahrain PDPL has imprisonment
                       provisions; India DPDPA caps at civil penalties; Kuwait
                       DPPR fines are mid-range.
  - enforcement_weight: how active the regulator has been historically. Kuwait
                       CITRA enforces breach rules aggressively; India DPB is
                       new; Bahrain PDPA is mature but moderate-volume.
  - impact_weight    : business impact of non-compliance for a bank — driven
                       by topic. consent + cross-border + breach are top-tier;
                       documentation gaps are mid-tier; aspirational
                       principles are bottom-tier.
  - coverage_factor  : 0=fully covered, 1=not covered, 0.5=partial. Multiplies
                       the underlying risk so a "not covered" Critical-impact
                       obligation is the maximum.

Why a function and not a JSONField config: weights are a legal/regulatory
judgement — they shouldn't be edited at runtime by analysts. Code-review
gating is the right control.
"""

from __future__ import annotations

# raw weights per jurisdiction. justification kept inline so reviewers can
# see why each number is what it is.
_PENALTY_BY_JURISDICTION: dict[str, float] = {
    # Bahrain PDPL: up to 1 year imprisonment + BD20k fines for serious
    # violations (Art 58-59). highest in the GCC privacy sphere.
    'bahrain': 0.95,
    # India DPDPA: up to INR 250 crore (~$30M) civil penalty per violation
    # but no imprisonment for DP offences. very large absolute number.
    'india':   0.90,
    # Kuwait DPPR: KWD 5-50k administrative fines; criminal penalties available
    # via the older Cybercrime Law 63/2015 for severe cases.
    'kuwait':  0.75,
    # default for unknown jurisdictions
    '':        0.60,
}

_ENFORCEMENT_BY_JURISDICTION: dict[str, float] = {
    # Bahrain PDPA: mature regulator, moderate enforcement volume.
    'bahrain': 0.80,
    # India DPB: new (created by DPDPA 2023), still ramping up.
    'india':   0.65,
    # Kuwait CITRA: active in cybersecurity; less in pure DP yet.
    'kuwait':  0.70,
    '':        0.55,
}

# topic-driven business impact for a banking-sector controller. these mirror
# the obligation categories that recur in BBK's regulatory landscape.
_IMPACT_BY_TOPIC: dict[str, float] = {
    # top tier — direct customer-facing risk + regulator hot buttons
    'consent':                     0.95,
    'breach':                      0.95,
    'breach_notification':         0.95,
    'cross_border':                0.90,
    'transfer':                    0.90,
    'sensitive_data':              0.95,
    'data_subject_rights':         0.85,
    'rights':                      0.85,
    'security':                    0.85,

    # mid tier — important controls but indirect customer impact
    'retention':                   0.75,
    'minimisation':                0.70,
    'purpose_limitation':          0.70,
    'lawful_basis':                0.75,
    'dpo':                         0.70,
    'data_protection_officer':     0.70,
    'dpia':                        0.70,
    'records_of_processing':       0.65,

    # accountability / governance — internal hygiene
    'accountability':              0.60,
    'notice':                      0.65,
    'privacy_notice':              0.65,
    'training':                    0.50,
    'audit':                       0.55,
    'governance':                  0.55,
}

# default impact when the topic isn't in the table (mid-tier, conservative).
_DEFAULT_IMPACT = 0.65

# coverage_factor multiplies the base risk: an obligation with no policy
# coverage is the most exposed; a fully covered one is essentially zero risk.
_COVERAGE_FACTOR: dict[str, float] = {
    'covered':           0.05,   # near-zero, but never zero (paper risk remains)
    'fully_covered':     0.05,
    'covered_full':      0.05,
    'partial':           0.55,
    'partially_covered': 0.55,
    'review':            0.65,   # uncertain mappings default to higher risk
    'requires_review':   0.65,
    'none':              1.00,   # no policy clause at all
    'not_covered':       1.00,
}

# bucket thresholds. tuning policy: top 5% → Critical, next 20% → High,
# next 40% → Medium, rest → Low. matches what BBK's risk register expects.
_BUCKET_THRESHOLDS = (
    ('Critical', 0.65),
    ('High',     0.45),
    ('Medium',   0.25),
    ('Low',      0.0),
)


def _normalise(s: str | None) -> str:
    return (s or '').strip().lower().replace('-', '_').replace(' ', '_')


def _topic_impact(topics: list[str] | None) -> float:
    """take the MAX impact across any topic flag attached to the obligation.
    a row tagged with both 'breach' (0.95) and 'governance' (0.55) gets the
    breach weight — the worse-case dominates for risk."""
    if not topics:
        return _DEFAULT_IMPACT
    impacts = [_IMPACT_BY_TOPIC.get(_normalise(t), _DEFAULT_IMPACT) for t in topics]
    return max(impacts) if impacts else _DEFAULT_IMPACT


def compute_risk_score(
    *,
    jurisdiction: str | None,
    coverage:     str | None,
    topics:       list[str] | None = None,
    confidence:   float | None = None,
) -> dict:
    """return a transparent dict explaining the multi-factor risk computation.

    keys:
      penalty_weight, enforcement_weight, impact_weight, coverage_factor — the
        four input multipliers, each in [0,1].
      score — final score in [0,1].
      bucket — one of Critical / High / Medium / Low.
      explanation — short human-readable justification suitable for tooltips.

    callers are encouraged to display the breakdown alongside the final
    bucket so analysts can audit every score rather than treating it as
    a black box.
    """
    jur_key  = _normalise(jurisdiction)
    cov_key  = _normalise(coverage)

    p = _PENALTY_BY_JURISDICTION.get(jur_key, _PENALTY_BY_JURISDICTION[''])
    e = _ENFORCEMENT_BY_JURISDICTION.get(jur_key, _ENFORCEMENT_BY_JURISDICTION[''])
    i = _topic_impact(topics)
    c = _COVERAGE_FACTOR.get(cov_key, 0.65)

    # geometric-style product of penalty × enforcement × impact, scaled by
    # coverage. avoids one big factor swamping the others.
    score = round(p * e * i * c, 3)

    bucket = 'Low'
    for name, threshold in _BUCKET_THRESHOLDS:
        if score >= threshold:
            bucket = name
            break

    # nudge up by AI confidence: a 95%-confident "not covered" claim is more
    # actionable than a 50%-confident one. cap the boost at 10% so a low-
    # confidence row can never tip into Critical purely on this factor.
    if confidence is not None:
        score = round(min(1.0, score * (0.9 + 0.1 * float(confidence))), 3)
        # re-bucket with the confidence-adjusted score
        for name, threshold in _BUCKET_THRESHOLDS:
            if score >= threshold:
                bucket = name
                break

    explanation = (
        f"penalty={p:.2f} (jurisdiction={jur_key or 'unknown'}) × "
        f"enforcement={e:.2f} × impact={i:.2f} (topic-driven) × "
        f"coverage_gap={c:.2f} = {score:.3f}"
    )

    return {
        'penalty_weight':     p,
        'enforcement_weight': e,
        'impact_weight':      i,
        'coverage_factor':    c,
        'score':              score,
        'bucket':             bucket,
        'explanation':        explanation,
    }


