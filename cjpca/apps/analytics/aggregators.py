"""
Coverage Heatmap aggregator — CJPCA analytics dashboard.

Aggregates approved ObligationMapping rows into an 11-principle × 3-jurisdiction
matrix.  Only MappingAnalysis rows with status == 'approved' are counted.

Principle tagging:
  1. Direct lookup via analysis.topic  (_TOPIC_TO_PRINCIPLE)
  2. Keyword fallback on obligation_title  (_infer_principle)
"""

from __future__ import annotations

# ── Constants (exported so views and tests can import them) ───────────────────

PRINCIPLES: list[str] = [
    "lawfulness_and_consent",
    "purpose_limitation",
    "data_minimization",
    "accuracy",
    "retention",
    "data_subject_rights",
    "cross_border_transfer",
    "breach_notification",
    "security_controls",
    "accountability_and_dpia",
    "vendor_and_processor",
]

JURISDICTIONS: list[str] = ["BH", "IN", "KW"]

JURISDICTION_MAP: dict[str, str] = {
    "bahrain": "BH",
    "india":   "IN",
    "kuwait":  "KW",
}

PRINCIPLE_LABELS: dict[str, str] = {
    "lawfulness_and_consent":  "Lawfulness & Consent",
    "purpose_limitation":      "Purpose Limitation",
    "data_minimization":       "Data Minimisation",
    "accuracy":                "Accuracy",
    "retention":               "Retention",
    "data_subject_rights":     "Data Subject Rights",
    "cross_border_transfer":   "Cross-Border Transfer",
    "breach_notification":     "Breach Notification",
    "security_controls":       "Security Controls",
    "accountability_and_dpia": "Accountability & DPIA",
    "vendor_and_processor":    "Vendor & Processor",
}

JUR_LABELS: dict[str, str] = {
    "BH": "Bahrain",
    "IN": "India",
    "KW": "Kuwait",
}

# ── Internal lookup tables ─────────────────────────────────────────────────────

# Maps MappingAnalysis.topic (exact string) → principle slug
_TOPIC_TO_PRINCIPLE: dict[str, str] = {
    "Consent":                  "lawfulness_and_consent",
    "Lawfulness of processing": "lawfulness_and_consent",
    "Data retention":           "retention",
    "Data subject rights":      "data_subject_rights",
    "Cross-border transfers":   "cross_border_transfer",
    "Security":                 "security_controls",
    "Breach notification":      "breach_notification",
    "Accountability":           "accountability_and_dpia",
}

# Ordered keyword → principle pairs for obligation_title fallback.
# More-specific entries come first to avoid false matches.
_TITLE_KEYWORDS: list[tuple[str, str]] = [
    ("cross-border",       "cross_border_transfer"),
    ("cross border",       "cross_border_transfer"),
    ("subject right",      "data_subject_rights"),
    ("individual right",   "data_subject_rights"),
    ("data minim",         "data_minimization"),
    ("minimis",            "data_minimization"),
    ("purpose limit",      "purpose_limitation"),
    ("accountability",     "accountability_and_dpia"),
    ("impact assess",      "accountability_and_dpia"),
    ("dpia",               "accountability_and_dpia"),
    ("vendor",             "vendor_and_processor"),
    ("processor",          "vendor_and_processor"),
    ("third party",        "vendor_and_processor"),
    ("breach",             "breach_notification"),
    ("incident notif",     "breach_notification"),
    ("retention",          "retention"),
    ("storage limit",      "retention"),
    ("transfer",           "cross_border_transfer"),
    ("security",           "security_controls"),
    ("consent",            "lawfulness_and_consent"),
    ("lawful",             "lawfulness_and_consent"),
    ("accura",             "accuracy"),
]

# Reverse map: principle → list of analysis topics (for gap register filtering)
PRINCIPLE_TO_TOPICS: dict[str, list[str]] = {
    "lawfulness_and_consent":  ["Consent", "Lawfulness of processing"],
    "retention":               ["Data retention"],
    "data_subject_rights":     ["Data subject rights"],
    "cross_border_transfer":   ["Cross-border transfers"],
    "security_controls":       ["Security"],
    "breach_notification":     ["Breach notification"],
    "accountability_and_dpia": ["Accountability"],
}


def accuracy_metrics(user=None) -> dict:
    """
    Compute AI accuracy feedback metrics from human review decisions.

    Uses ComparisonResult lifecycle (approved/rejected) as ground truth:
      approved → AI was correct
      rejected → AI was wrong

    When ``user`` is supplied and is an *analyst*, the metrics are restricted
    to ComparisonResult/AuditEvent rows from runs they themselves created.
    Reviewers/admins (or no user) see the full dataset.

    Returns calibration data (confidence bucket vs actual approval rate),
    per-reviewer stats, and a monthly accuracy trend.
    """
    import calendar
    from datetime import datetime

    from django.db.models import Count, Max, Q
    from django.utils import timezone

    from apps.comparison.models import AuditEvent, ComparisonResult

    now = timezone.now()

    # Decide whether to scope to a single analyst's runs.
    scope_user = None
    if user is not None and getattr(user, 'is_authenticated', False):
        try:
            from apps.accounts.decorators import get_user_role
            if get_user_role(user) == 'analyst':
                scope_user = user
        except ImportError:
            pass

    cr_qs = ComparisonResult.objects.all()
    ae_qs = AuditEvent.objects.all()
    if scope_user is not None:
        cr_qs = cr_qs.filter(run__created_by=scope_user)
        ae_qs = ae_qs.filter(result__run__created_by=scope_user)

    # ── Confidence calibration ────────────────────────────────────────────────
    # 10 buckets: 0-10%, 10-20%, ..., 90-100%
    buckets: list[dict] = [
        {'band': f'{i * 10}–{i * 10 + 10}%', 'mid': i * 10 + 5,
         'approved': 0, 'total': 0}
        for i in range(10)
    ]
    for r in cr_qs.filter(
        lifecycle__in=[ComparisonResult.APPROVED, ComparisonResult.REJECTED]
    ).only('confidence', 'lifecycle'):
        idx = min(int(r.confidence * 10), 9)
        buckets[idx]['total'] += 1
        if r.lifecycle == ComparisonResult.APPROVED:
            buckets[idx]['approved'] += 1

    for b in buckets:
        b['approval_rate'] = (
            round(b['approved'] / b['total'] * 100) if b['total'] else None
        )

    # ── Per-reviewer stats ────────────────────────────────────────────────────
    reviewer_rows = (
        ae_qs
        .filter(action__in=['approved', 'rejected'])
        .exclude(actor='system')
        .values('actor')
        .annotate(
            n_approved=Count('id', filter=Q(action='approved')),
            n_rejected=Count('id', filter=Q(action='rejected')),
            last_active=Max('timestamp'),
        )
        .order_by('-n_approved')[:10]
    )
    reviewer_stats = []
    for row in reviewer_rows:
        total = row['n_approved'] + row['n_rejected']
        reviewer_stats.append({
            'actor':        row['actor'],
            'approved':     row['n_approved'],
            'rejected':     row['n_rejected'],
            'total':        total,
            'accuracy_pct': round(row['n_approved'] / total * 100) if total else 0,
            'last_active':  (
                row['last_active'].strftime('%d %b %Y')
                if row['last_active'] else '—'
            ),
        })

    # ── Monthly accuracy trend (last 6 months) ────────────────────────────────
    monthly_labels: list[str] = []
    monthly_values: list[int | None] = []
    for i in range(5, -1, -1):
        yr = now.year + (now.month - 1 - i) // 12
        mo = (now.month - 1 - i) % 12 + 1
        start_dt = timezone.make_aware(datetime(yr, mo, 1))
        end_dt   = timezone.make_aware(
            datetime(yr, mo, calendar.monthrange(yr, mo)[1], 23, 59, 59)
        )
        monthly_labels.append(start_dt.strftime('%b'))
        n_app = ae_qs.filter(
            action='approved', timestamp__gte=start_dt, timestamp__lte=end_dt,
        ).count()
        n_rej = ae_qs.filter(
            action='rejected', timestamp__gte=start_dt, timestamp__lte=end_dt,
        ).count()
        total_mo = n_app + n_rej
        monthly_values.append(round(n_app / total_mo * 100) if total_mo else None)

    # ── Overall summary ───────────────────────────────────────────────────────
    total_reviewed = sum(b['total'] for b in buckets)
    total_approved = sum(b['approved'] for b in buckets)
    overall_accuracy = (
        round(total_approved / total_reviewed * 100) if total_reviewed else 0
    )

    return {
        'calibration':     buckets,
        'reviewer_stats':  reviewer_stats,
        'monthly_accuracy': {
            'labels': monthly_labels,
            'values': monthly_values,
        },
        'total_reviewed':  total_reviewed,
        'overall_accuracy': overall_accuracy,
    }


def _infer_principle(title: str) -> str | None:
    """Keyword-match obligation_title to a principle slug. Returns None on no match."""
    lower = title.lower()
    for keyword, principle in _TITLE_KEYWORDS:
        if keyword in lower:
            return principle
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def coverage_heatmap(user=None) -> dict:
    """
    Return the heatmap data contract.

    When ``user`` is an *analyst*, the cell totals only reflect
    ObligationMapping rows whose parent MappingAnalysis was created by that
    user. Reviewers/admins (or no user) see the full approved corpus.

    Always returns exactly 33 cells (11 × 3), even when there is no data
    (every missing cell has status "grey" and coverage_pct None).

    Return shape:
        {
            "principles":    list[str],   # 11 slugs, ordered
            "jurisdictions": list[str],   # ["BH", "IN", "KW"]
            "cells": [
                {
                    "principle":    str,
                    "jurisdiction": str,
                    "total":        int,
                    "covered":      int,
                    "partial":      int,
                    "not_covered":  int,          # NONE + REVIEW
                    "coverage_pct": float | None, # None when total == 0
                    "status":       "green" | "amber" | "red" | "grey",
                },
                ...  # 33 entries
            ]
        }
    """
    from apps.mapping.models import MappingAnalysis, ObligationMapping

    # Seed every (principle, jurisdiction) cell so output always has 33 entries
    cell_data: dict[tuple[str, str], dict] = {
        (p, j): {"covered": 0, "partial": 0, "not_covered": 0, "total": 0}
        for p in PRINCIPLES
        for j in JURISDICTIONS
    }

    scope_user = None
    if user is not None and getattr(user, 'is_authenticated', False):
        try:
            from apps.accounts.decorators import get_user_role
            if get_user_role(user) == 'analyst':
                scope_user = user
        except ImportError:
            pass

    obligations = (
        ObligationMapping.objects
        .filter(analysis__status=MappingAnalysis.APPROVED)
        .select_related("analysis", "regulation")
        .only(
            "coverage",
            "obligation_title",
            "analysis__status",
            "analysis__topic",
            "regulation__jurisdiction",
        )
    )
    if scope_user is not None:
        obligations = obligations.filter(analysis__created_by=scope_user)

    for ob in obligations:
        jur_code = JURISDICTION_MAP.get(ob.regulation.jurisdiction)
        if jur_code not in JURISDICTIONS:
            continue

        principle = (
            _TOPIC_TO_PRINCIPLE.get(ob.analysis.topic)
            or _infer_principle(ob.obligation_title)
        )
        if not principle or principle not in PRINCIPLES:
            continue

        key = (principle, jur_code)
        cell_data[key]["total"] += 1

        if ob.coverage == ObligationMapping.COVERED:
            cell_data[key]["covered"] += 1
        elif ob.coverage == ObligationMapping.PARTIAL:
            cell_data[key]["partial"] += 1
        else:
            cell_data[key]["not_covered"] += 1

    # Build ordered output list
    result_cells: list[dict] = []
    for p in PRINCIPLES:
        for j in JURISDICTIONS:
            d = cell_data[(p, j)]
            total = d["total"]

            if total > 0:
                pct = (d["covered"] + 0.5 * d["partial"]) / total * 100
                if pct >= 80:
                    status = "green"
                elif pct >= 40:
                    status = "amber"
                else:
                    status = "red"
                pct_out: float | None = round(pct, 1)
            else:
                pct_out = None
                status = "grey"

            result_cells.append({
                "principle":    p,
                "jurisdiction": j,
                "total":        total,
                "covered":      d["covered"],
                "partial":      d["partial"],
                "not_covered":  d["not_covered"],
                "coverage_pct": pct_out,
                "status":       status,
            })

    return {
        "principles":    PRINCIPLES,
        "jurisdictions": JURISDICTIONS,
        "cells":         result_cells,
    }
