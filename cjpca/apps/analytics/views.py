import json
import calendar
from collections import Counter
from datetime import datetime, timedelta

from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.decorators import role_required, get_user_role
from apps.library.models import Document
from apps.comparison.models import (
    ComparisonRun, ComparisonResult,
    REL_COLORS, REL_LABELS,
)
from apps.mapping.models import MappingAnalysis, ObligationMapping, Gap

ALL_ROLES = ('analyst', 'reviewer', 'admin')


def scoped_results_qs(user):
    """ComparisonResult queryset scoped by role.

    Analysts only see results from runs they themselves created. Reviewer
    and admin see the full dataset. Anonymous users get an empty queryset
    (in practice they never reach these views, but be defensive).
    """
    qs = ComparisonResult.objects.all()
    if not user or not user.is_authenticated:
        return qs.none()
    if get_user_role(user) == 'analyst':
        return qs.filter(run__created_by=user)
    return qs


def scoped_runs_qs(user):
    qs = ComparisonRun.objects.all()
    if not user or not user.is_authenticated:
        return qs.none()
    if get_user_role(user) == 'analyst':
        return qs.filter(created_by=user)
    return qs


def _last_delta(series):
    """Month-over-month change from a numeric time-series (last vs previous).
    Returns None when there isn't enough history — so the UI shows a delta ONLY
    when it's real, never a fabricated one."""
    vals = [v for v in (series or [])]
    if len(vals) < 2:
        return None
    cur, prev = vals[-1], vals[-2]
    # A month with no data (None) has no honest delta to show.
    if cur is None or prev is None:
        return None
    diff = cur - prev
    pct = (round(diff / prev * 100) if prev else None)
    return {
        'cur': cur, 'prev': prev, 'diff': diff, 'pct': pct,
        'mag_diff': abs(diff),
        'mag_pct': (abs(pct) if pct is not None else None),
        'dir': 'up' if diff > 0 else ('down' if diff < 0 else 'flat'),
    }


def _month_window(year, month):
    start = timezone.make_aware(datetime(year, month, 1))
    last  = calendar.monthrange(year, month)[1]
    end   = timezone.make_aware(datetime(year, month, last, 23, 59, 59))
    return start, end


# Internal relationship types (all 6 stored in DB)
REL_TYPES = [
    ComparisonResult.EQUIVALENT,
    ComparisonResult.STRICTER_IN_A,
    ComparisonResult.STRICTER_IN_B,
    ComparisonResult.ADDITIONAL_IN_A,
    ComparisonResult.ADDITIONAL_IN_B,
    ComparisonResult.CONFLICTING,
]

# 4-category display groups — A/B distinction is meaningless in aggregate
DISPLAY_GROUPS = [
    ('equivalent',  'Equivalent',  '#FFB800', [ComparisonResult.EQUIVALENT]),
    ('stricter',    'One Side Stricter', '#002583', [ComparisonResult.STRICTER_IN_A, ComparisonResult.STRICTER_IN_B]),
    ('additional',  'Additional Clause', '#FFB800', [ComparisonResult.ADDITIONAL_IN_A, ComparisonResult.ADDITIONAL_IN_B]),
    ('conflicting', 'Conflicting', '#002583', [ComparisonResult.CONFLICTING]),
]

PAIRS = [
    ('bh_in', 'BH ↔ IN'),
    ('bh_kw', 'BH ↔ KW'),
    ('in_kw', 'IN ↔ KW'),
]


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class AnalyticsView(TemplateView):
    template_name = 'pages/analytics.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()

        # Role scope: analysts see only their own runs/results; reviewer +
        # admin see everything. This is enforced at queryset level so the
        # JSON refresh endpoint and any direct-API calls also stay scoped.
        cr_qs   = scoped_results_qs(self.request.user)
        crun_qs = scoped_runs_qs(self.request.user)

        # ── Core counts ──────────────────────────────────────────────────────
        total_results = cr_qs.count()
        total_runs    = crun_qs.count()
        complete_runs = crun_qs.filter(status=ComparisonRun.COMPLETE).count()
        failed_runs   = crun_qs.filter(status=ComparisonRun.FAILED).count()

        # ── Relationship breakdown (4-group display) ─────────────────────────
        rel_counts = {
            r: cr_qs.filter(relationship=r).count()
            for r in REL_TYPES
        }
        equivalent_pct    = round(rel_counts[ComparisonResult.EQUIVALENT] / total_results * 100) if total_results else 0
        conflicting_count = rel_counts[ComparisonResult.CONFLICTING]

        rel_breakdown = [
            {
                'key':   gkey,
                'label': glabel,
                'color': gcolor,
                'count': sum(rel_counts[r] for r in grels),
                'pct':   round(sum(rel_counts[r] for r in grels) / total_results * 100) if total_results else 0,
            }
            for gkey, glabel, gcolor, grels in DISPLAY_GROUPS
        ]

        # ── Average confidence ───────────────────────────────────────────────
        avg_conf         = cr_qs.aggregate(avg=Avg('confidence'))['avg'] or 0
        avg_confidence_pct = round(avg_conf * 100)

        # ── Lifecycle breakdown ──────────────────────────────────────────────
        lc_counts = {
            lc: cr_qs.filter(lifecycle=lc).count()
            for lc in [ComparisonResult.DRAFT, ComparisonResult.REVIEWED,
                       ComparisonResult.APPROVED, ComparisonResult.REJECTED]
        }
        approved_count = lc_counts[ComparisonResult.APPROVED]
        rejected_count = lc_counts[ComparisonResult.REJECTED]
        reviewed_total = approved_count + rejected_count
        ai_accuracy    = round(approved_count / reviewed_total * 100) if reviewed_total else 0

        # ── Relationship by jurisdiction pair (4-group) ───────────────────────
        pair_data = []
        for pk, pl in PAIRS:
            raw = {
                r: cr_qs.filter(run__pair_key=pk, relationship=r).count()
                for r in REL_TYPES
            }
            total = sum(raw.values())
            rows = [
                {
                    'key':   gkey,
                    'label': glabel,
                    'color': gcolor,
                    'count': sum(raw[r] for r in grels),
                    'pct':   round(sum(raw[r] for r in grels) / total * 100) if total else 0,
                }
                for gkey, glabel, gcolor, grels in DISPLAY_GROUPS
            ]
            pair_data.append({'key': pk, 'label': pl, 'counts': raw, 'total': total, 'rows': rows})

        # ── Confidence distribution (10 buckets) ─────────────────────────────
        conf_buckets = [0] * 10
        for result in cr_qs.only('confidence'):
            bucket = min(int(result.confidence * 10), 9)
            conf_buckets[bucket] += 1

        # ── Avg confidence by display group ─────────────────────────────────
        avg_conf_by_rel = []
        for gkey, glabel, gcolor, grels in DISPLAY_GROUPS:
            qs_avg = cr_qs.filter(relationship__in=grels).aggregate(avg=Avg('confidence'))
            avg_conf_by_rel.append(round((qs_avg['avg'] or 0) * 100))

        # ── Single-pass: top principles, radar, heatmap ─────────────────────
        # SQLite JSONField __contains is unsupported — do everything in Python
        RADAR_PRINCIPLES = [
            ('consent',              'Consent'),
            ('breach',               'Breach'),
            ('data_subject',         'Data Rights'),
            ('data_controller',      'Controller'),
            ('cross_border_transfer','Transfers'),
            ('retention',            'Retention'),
        ]
        HEATMAP_PIDS = [
            ('consent',              'Consent'),
            ('breach',               'Breach Notif.'),
            ('data_subject',         'Data Rights'),
            ('cross_border_transfer','Cross-Border'),
            ('retention',            'Retention'),
            ('data_controller',      'Controller'),
            ('processing_grounds',   'Processing Basis'),
            ('vendor_processor',     'Processor'),
        ]
        heatmap_pair_keys = [pk for pk, _ in PAIRS]

        principle_counter = Counter()
        radar_totals = {pid: 0 for pid, _ in RADAR_PRINCIPLES}
        radar_equiv  = {pid: 0 for pid, _ in RADAR_PRINCIPLES}
        hm = {
            (pid, pk): {'total': 0, 'equiv': 0}
            for pid, _ in HEATMAP_PIDS
            for pk in heatmap_pair_keys
        }

        for result in cr_qs.select_related('run').only(
            'principle_ids', 'relationship', 'run__pair_key'
        ):
            pids     = result.principle_ids or []
            pair_key = result.run.pair_key
            for pid in pids:
                principle_counter[pid] += 1
                if pid in radar_totals:
                    radar_totals[pid] += 1
                    if result.relationship == ComparisonResult.EQUIVALENT:
                        radar_equiv[pid] += 1
                if (pid, pair_key) in hm:
                    hm[(pid, pair_key)]['total'] += 1
                    if result.relationship == ComparisonResult.EQUIVALENT:
                        hm[(pid, pair_key)]['equiv'] += 1

        top_principles = principle_counter.most_common(8)

        radar_labels = [plabel for _, plabel in RADAR_PRINCIPLES]
        radar_values = [
            round(radar_equiv[pid] / radar_totals[pid] * 100) if radar_totals[pid] else 0
            for pid, _ in RADAR_PRINCIPLES
        ]

        # ── Heatmap rows (principle × pair) ──────────────────────────────────
        def _cell_style(pct):
            if pct is None:
                return 'grey',  '#E5E8EF', '#D1D5E0'
            if pct >= 70:
                return 'green', '#E5E8EF', '#002583'
            if pct >= 40:
                return 'amber', '#E5E8EF', '#002583'
            return 'red',       '#E5E8EF', '#002583'

        heatmap_rows = []
        for pid, plabel in HEATMAP_PIDS:
            cells = []
            for pair_key, pair_label in PAIRS:
                d     = hm[(pid, pair_key)]
                total = d['total']
                equiv = d['equiv']
                pct   = round(equiv / total * 100) if total else None
                status, bg, fg = _cell_style(pct)
                cells.append({
                    'pair_label': pair_label,
                    'total': total,
                    'equiv': equiv,
                    'pct':   pct,
                    'status': status,
                    'bg': bg,
                    'fg': fg,
                })
            heatmap_rows.append({'label': plabel, 'cells': cells})

        # ── Runs over time + gap trend (last 6 months) ───────────────────────
        from apps.comparison.models import AuditEvent
        ae_qs = AuditEvent.objects.all()
        if get_user_role(self.request.user) == 'analyst':
            ae_qs = ae_qs.filter(result__run__created_by=self.request.user)

        month_labels, runs_per_month, results_per_month = [], [], []
        gap_trend_identified, gap_trend_resolved = [], []
        for i in range(5, -1, -1):
            yr = now.year + (now.month - 1 - i) // 12
            mo = (now.month - 1 - i) % 12 + 1
            start, end = _month_window(yr, mo)
            month_labels.append(start.strftime('%b'))
            runs_per_month.append(
                crun_qs.filter(
                    status=ComparisonRun.COMPLETE,
                    created_at__gte=start, created_at__lte=end,
                ).count()
            )
            results_per_month.append(
                cr_qs.filter(
                    created_at__gte=start, created_at__lte=end,
                ).count()
            )
            gap_trend_identified.append(
                cr_qs.filter(
                    relationship=ComparisonResult.CONFLICTING,
                    created_at__gte=start, created_at__lte=end,
                ).count()
            )
            gap_trend_resolved.append(
                ae_qs.filter(
                    action='approved',
                    timestamp__gte=start, timestamp__lte=end,
                ).count()
            )

        # ── Remediation velocity (approvals per week, last 8 weeks) ──────────
        remed_labels, remed_values = [], []
        for i in range(7, -1, -1):
            wk_start = now - timedelta(days=7 * (i + 1))
            wk_end   = now - timedelta(days=7 * i)
            cnt = ae_qs.filter(
                action='approved',
                timestamp__gte=wk_start,
                timestamp__lt=wk_end,
            ).count()
            remed_labels.append(f'W{8 - i}')
            remed_values.append(cnt)

        # ── Compliance % per completed run ────────────────────────────────────
        runs = list(
            crun_qs.filter(status=ComparisonRun.COMPLETE)
            .order_by('created_at')[:12]
        )
        comp_labels = [f'Run {r.pk}' for r in runs]
        comp_values = []
        for run in runs:
            tr = run.results.count()
            eq = run.results.filter(relationship=ComparisonResult.EQUIVALENT).count()
            comp_values.append(round(eq / tr * 100) if tr else 0)
        if not comp_labels:
            comp_labels = month_labels
            comp_values = [0] * len(month_labels)

        # ── Recent conflicting clause pairs ───────────────────────────────────
        conflicting_results = list(
            cr_qs
            .filter(relationship=ComparisonResult.CONFLICTING)
            .select_related('run', 'run__reg_a', 'run__reg_b')
            .order_by('-confidence')[:12]
        )

        # ── AI accuracy feedback metrics ─────────────────────────────────────
        acc = accuracy_metrics(user=self.request.user)

        # ── Honest header meta + month-over-month deltas ─────────────────────
        # Everything here is derived from real data — no fabricated trend %.
        from apps.library.models import Document as _Doc2
        meta_jurisdictions = (
            _Doc2.objects.exclude(jurisdiction='').values('jurisdiction').distinct().count()
        )
        meta_policies = _Doc2.objects.filter(doc_type=_Doc2.POLICY).count()
        meta_regulations = _Doc2.objects.filter(doc_type=_Doc2.REGULATION).count()
        meta_last_updated = (
            crun_qs.order_by('-created_at').values_list('created_at', flat=True).first()
        )
        # Is the accuracy metric trustworthy enough to feature? A tiny review
        # sample (e.g. 1 approval → "100%") reads as a hallucinated flex, so we
        # only surface the score once there's a real sample behind it.
        _acc_vals = acc['monthly_accuracy'].get('values') or []
        accuracy_has_data = any(v is not None for v in _acc_vals)
        accuracy_reliable = acc['total_reviewed'] >= 5

        # real deltas (None when there isn't enough history)
        accuracy_delta  = _last_delta(_acc_vals)
        conflicts_delta = _last_delta(gap_trend_identified)   # new conflicts this month vs last
        resolved_delta  = _last_delta(gap_trend_resolved)     # approvals this month vs last
        activity_delta  = _last_delta(results_per_month)

        # ── Chart data JSON ───────────────────────────────────────────────────
        chart_data = {
            'relationshipBreakdown': {
                'labels': [g['label'] for g in rel_breakdown],
                'values': [g['count'] for g in rel_breakdown],
                'colors': [g['color'] for g in rel_breakdown],
            },
            'relationshipByPair': {
                'pairs':  [p['label'] for p in pair_data],
                'data':   {g['key']: [p['rows'][i]['count'] for p in pair_data]
                           for i, g in enumerate(rel_breakdown)},
                'labels': [g['label'] for g in rel_breakdown],
                'colors': [g['color'] for g in rel_breakdown],
            },
            'confidenceDistribution': {
                'labels': [f'{i*10}–{i*10+10}%' for i in range(10)],
                'values': conf_buckets,
            },
            'lifecycleStatus': {
                'labels': ['Draft', 'Reviewed', 'Approved', 'Rejected'],
                'values': [
                    lc_counts[ComparisonResult.DRAFT],
                    lc_counts[ComparisonResult.REVIEWED],
                    lc_counts[ComparisonResult.APPROVED],
                    lc_counts[ComparisonResult.REJECTED],
                ],
            },
            'runsOverTime': {
                'labels':  month_labels,
                'runs':    runs_per_month,
                'results': results_per_month,
            },
            'avgConfidenceByRel': {
                'labels': [g[1] for g in DISPLAY_GROUPS],
                'values': avg_conf_by_rel,
                'colors': [g[2] for g in DISPLAY_GROUPS],
            },
            'topPrinciples': {
                'labels': [p[0] for p in top_principles],
                'values': [p[1] for p in top_principles],
            },
            'complianceByRun': {
                'labels': comp_labels,
                'values': comp_values,
            },
            'radar': {
                'labels': radar_labels,
                'values': radar_values,
            },
            'gapTrend': {
                'labels':     month_labels,
                'identified': gap_trend_identified,
                'resolved':   gap_trend_resolved,
            },
            'remediationVelocity': {
                'labels': remed_labels,
                'values': remed_values,
            },
            'calibration': {
                'labels':  [b['band'] for b in acc['calibration']],
                'ai_conf': [b['mid']  for b in acc['calibration']],
                'actual':  [b['approval_rate'] for b in acc['calibration']],
                'counts':  [b['total'] for b in acc['calibration']],
            },
            'accuracyTrend': acc['monthly_accuracy'],
        }

        # AI accuracy bars (lifecycle-based)
        rev_denominator = approved_count + rejected_count + lc_counts[ComparisonResult.REVIEWED]
        ai_bars = [
            {
                'label': 'Approved',
                'count': approved_count,
                'pct':   round(approved_count / reviewed_total * 100) if reviewed_total else 0,
                'color': '#FFB800',
                'bg':    '#1D9E7570',
            },
            {
                'label': 'Pending review',
                'count': lc_counts[ComparisonResult.REVIEWED],
                'pct':   round(lc_counts[ComparisonResult.REVIEWED] / rev_denominator * 100) if rev_denominator else 0,
                'color': '#002583',
                'bg':    '#7C3AED70',
            },
            {
                'label': 'Rejected',
                'count': rejected_count,
                'pct':   round(rejected_count / reviewed_total * 100) if reviewed_total else 0,
                'color': '#002583',
                'bg':    '#DC262670',
            },
        ]

        # ── Policy Mapping aggregation ───────────────────────────────────────
        # Pulls MappingAnalysis runs into the analytics dashboard. Same
        # role-scoping rule as comparison: analysts see only their own runs;
        # reviewer + admin see everything.
        #
        # IMPORTANT: include COMPLETE, REVIEW, and APPROVED. Previously this
        # filtered for COMPLETE only, which meant a mapping disappeared from
        # the analytics tab the moment a reviewer validated it (status flips
        # to APPROVED). That was backwards — approved mappings are exactly
        # the ones that should weight the most in compliance reporting.
        ma_qs = MappingAnalysis.objects.filter(status__in=[
            MappingAnalysis.COMPLETE,
            MappingAnalysis.REVIEW,
            MappingAnalysis.APPROVED,
        ])
        if get_user_role(self.request.user) == 'analyst':
            ma_qs = ma_qs.filter(created_by=self.request.user)

        om_qs = ObligationMapping.objects.filter(analysis__in=ma_qs)
        gap_qs = Gap.objects.filter(mapping__in=ma_qs)

        mapping_total = ma_qs.count()
        mapping_obligations = om_qs.count()
        mapping_gaps = gap_qs.count()

        # Coverage breakdown across all obligations (parallel to comparison's
        # rel_breakdown — these are the four colour categories).
        mc = {
            'covered': om_qs.filter(coverage=ObligationMapping.COVERED).count(),
            'partial': om_qs.filter(coverage=ObligationMapping.PARTIAL).count(),
            'review':  om_qs.filter(coverage=ObligationMapping.REVIEW).count(),
            'none':    om_qs.filter(coverage=ObligationMapping.NONE).count(),
        }
        mapping_compliance_pct = (
            round((mc['covered'] + 0.5 * mc['partial']) / mapping_obligations * 100)
            if mapping_obligations else 0
        )
        # coverage progress (covered obligations of total) — real, drives the KPI bar
        coverage_done  = mc['covered']
        coverage_total = mapping_obligations

        # AI quality: per-row citation_verified + hallucination_risk averages.
        verified_om = om_qs.filter(citation_verified=True).count()
        mapping_verified_pct = round(verified_om / mapping_obligations * 100) if mapping_obligations else 0
        avg_hall = om_qs.aggregate(avg=Avg('hallucination_risk'))['avg'] or 0.0
        mapping_ai_quality_pct = round(0.7 * mapping_verified_pct + 0.3 * (1.0 - avg_hall) * 100)

        # Per-jurisdiction coverage rollup. The regulation jurisdiction is on
        # ObligationMapping.regulation, not on the mapping analysis itself
        # (one analysis can map against multiple jurisdictions).
        jur_rows = []
        from apps.library.models import Document as _Doc
        jurisdictions_seen = (
            om_qs.values_list('regulation__jurisdiction', flat=True)
            .distinct()
        )
        for jur in jurisdictions_seen:
            if not jur:
                continue
            sub = om_qs.filter(regulation__jurisdiction=jur)
            sub_total = sub.count()
            if not sub_total:
                continue
            sub_cov = sub.filter(coverage=ObligationMapping.COVERED).count()
            sub_par = sub.filter(coverage=ObligationMapping.PARTIAL).count()
            sub_none = sub.filter(coverage=ObligationMapping.NONE).count()
            jur_rows.append({
                'jurisdiction': jur,
                'label':        jur.title() if jur != 'bbk' else 'BBK',
                'total':        sub_total,
                'covered':      sub_cov,
                'partial':      sub_par,
                'gaps':         sub_none,
                'pct':          round((sub_cov + 0.5 * sub_par) / sub_total * 100),
            })
        jur_rows.sort(key=lambda r: -r['pct'])

        # ── Auto-surfaced "Key Insights" for the Coverage tab ─────────────────
        # Every insight is derived from real numbers — a deterministic anomaly
        # surface, not an LLM narrative and not fabricated.
        coverage_insights = []
        if total_results and rel_breakdown:
            top_group = max(rel_breakdown, key=lambda g: g['count'])
            coverage_insights.append({
                'tone': 'blue',
                'title': f"{top_group['label']} is the most common outcome",
                'detail': f"{top_group['count']} of {total_results} clause pairs ({top_group['pct']}%) are {top_group['label'].lower()}.",
            })
        _conf_pairs = [(pd['label'], pd['counts'].get(ComparisonResult.CONFLICTING, 0)) for pd in pair_data]
        _conf_pairs = [p for p in _conf_pairs if p[1] > 0]
        if _conf_pairs:
            _hot = max(_conf_pairs, key=lambda p: p[1])
            coverage_insights.append({
                'tone': 'red',
                'title': f"Most conflicts are in {_hot[0]}",
                'detail': f"{_hot[1]} of {conflicting_count} conflicting pairs involve the {_hot[0]} jurisdictions.",
            })
        elif conflicting_count == 0 and total_results:
            coverage_insights.append({
                'tone': 'green',
                'title': "No conflicts detected",
                'detail': "Every compared clause is equivalent or stricter — nothing contradicts across jurisdictions.",
            })
        _low = sum(conf_buckets[:6])   # buckets 0–60%
        if total_results and _low:
            coverage_insights.append({
                'tone': 'amber',
                'title': f"{round(_low / total_results * 100)}% of pairs scored under 60% confidence",
                'detail': f"{_low} clause pair{'s' if _low != 1 else ''} fall below 60% — worth a human spot-check.",
            })
        if jur_rows:
            _weak = min(jur_rows, key=lambda r: r['pct'])
            coverage_insights.append({
                'tone': 'amber' if _weak['pct'] < 80 else 'green',
                'title': f"{_weak['label']} has the {'lowest ' if len(jur_rows) > 1 else ''}coverage at {_weak['pct']}%",
                'detail': f"{_weak['gaps']} of {_weak['total']} obligations in {_weak['label']} are uncovered.",
            })
        coverage_insights = coverage_insights[:5]

        # Per-policy roll-up. One row per BBK policy, showing total
        # obligations mapped, gap count, score, and last-run timestamp.
        policy_rows = []
        for ma in ma_qs.select_related('policy_doc').order_by('-completed_at'):
            ma_oms = om_qs.filter(analysis=ma)
            t = ma_oms.count()
            if not t:
                continue
            cov = ma_oms.filter(coverage=ObligationMapping.COVERED).count()
            par = ma_oms.filter(coverage=ObligationMapping.PARTIAL).count()
            policy_rows.append({
                'pk':            ma.pk,
                'policy_name':   ma.policy_doc.name,
                'completed_at':  ma.completed_at,
                'obligation_count': ma.obligation_count,
                'gap_count':     ma.gap_count,
                'score':         round((cov + 0.5 * par) / t * 100) if t else 0,
            })

        # High-priority gaps (Critical + High) currently open across all
        # analyses — these are the rows the legal team should be acting on.
        urgent_gaps = list(
            gap_qs
            .filter(priority__in=[Gap.CRITICAL, Gap.HIGH])
            .filter(closed_at__isnull=True)
            .select_related('obligation_mapping', 'obligation_mapping__regulation', 'mapping__policy_doc')
            .order_by('-mapping__completed_at')[:8]
        )

        # ── Unified action register ──────────────────────────────────────────
        # Merge open policy-mapping gaps and unresolved clause conflicts into
        # one severity-ranked list that drives the dashboard.
        from apps.analytics.actions import build_action_register
        action_items = build_action_register(self.request.user)
        action_critical = sum(1 for a in action_items if a['priority'] == 'critical')
        action_high     = sum(1 for a in action_items if a['priority'] == 'high')
        action_total    = len(action_items)

        mapping_chart_data = {
            'coverage': {
                'labels': ['Covered', 'Partial', 'Review', 'Not covered'],
                'values': [mc['covered'], mc['partial'], mc['review'], mc['none']],
                'colors': ['#1E7E48', '#FFB800', '#002583', '#C03A3A'],
            },
            'byJurisdiction': {
                'labels':  [r['label'] for r in jur_rows],
                'covered': [r['covered'] for r in jur_rows],
                'partial': [r['partial'] for r in jur_rows],
                'gaps':    [r['gaps'] for r in jur_rows],
            },
        }

        ctx.update({
            # Mapping KPIs
            'mapping_total':           mapping_total,
            'mapping_obligations':     mapping_obligations,
            'mapping_gaps':            mapping_gaps,
            'mapping_compliance_pct':  mapping_compliance_pct,
            'mapping_ai_quality_pct':  mapping_ai_quality_pct,
            'mapping_verified_pct':    mapping_verified_pct,
            'mapping_avg_hall':        round(avg_hall, 2),
            # Mapping breakdown
            'mapping_counts':          mc,
            'mapping_jurisdictions':   jur_rows,
            'mapping_policy_rows':     policy_rows,
            'mapping_urgent_gaps':     urgent_gaps,
            'mapping_chart_data':      json.dumps(mapping_chart_data),
            # Unified action register (gaps + conflicts, severity-ranked)
            'action_items':            action_items,
            'action_critical':         action_critical,
            'action_high':             action_high,
            'action_total':            action_total,
            # Header meta + honest deltas
            'meta_jurisdictions':      meta_jurisdictions,
            'meta_policies':           meta_policies,
            'meta_regulations':        meta_regulations,
            'meta_last_updated':       meta_last_updated,
            'accuracy_delta':          accuracy_delta,
            'accuracy_has_data':       accuracy_has_data,
            'accuracy_reliable':       accuracy_reliable,
            'conflicts_delta':         conflicts_delta,
            'resolved_delta':          resolved_delta,
            'activity_delta':          activity_delta,
            'coverage_done':           coverage_done,
            'coverage_total':          coverage_total,
        })

        ctx.update({
            # KPIs
            'equivalent_pct':      equivalent_pct,
            'conflicting_count':   conflicting_count,
            'avg_confidence_pct':  avg_confidence_pct,
            'coverage_insights':   coverage_insights,
            'spark_conflicts':     gap_trend_identified,
            'spark_conflicts_max': max(gap_trend_identified) if gap_trend_identified else 0,
            'ai_accuracy':         ai_accuracy,
            'total_results':       total_results,
            'total_runs':          total_runs,
            'complete_runs':       complete_runs,
            'failed_runs':         failed_runs,
            # Breakdown
            'rel_breakdown':       rel_breakdown,
            'pair_data':           pair_data,
            # Lifecycle
            'approved_count':      approved_count,
            'rejected_count':      rejected_count,
            'reviewed_total':      reviewed_total,
            'lc_draft':            lc_counts[ComparisonResult.DRAFT],
            'lc_reviewed':         lc_counts[ComparisonResult.REVIEWED],
            # AI accuracy bars
            'ai_bars':             ai_bars,
            'rev_denominator':     rev_denominator,
            # Heatmap
            'heatmap_rows':        heatmap_rows,
            'heatmap_pairs':       [pl for _, pl in PAIRS],
            # Conflict table
            'conflicting_results': conflicting_results,
            # Chart data
            'chart_data': json.dumps(chart_data),
            # AI accuracy feedback
            'reviewer_stats':     acc['reviewer_stats'],
            'acc_total_reviewed': acc['total_reviewed'],
            'acc_overall':        acc['overall_accuracy'],
        })
        return ctx


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class AnalyticsDataView(View):
    """GET /analytics/data/ — JSON refresh endpoint."""
    def get(self, request):
        view = AnalyticsView()
        view.request = request
        view.args = ()
        view.kwargs = {}
        ctx = view.get_context_data()
        return JsonResponse(json.loads(ctx['chart_data']))


# ── Heatmap views (kept, using mapping models — shows grey when no data) ────────

from django.contrib.auth.mixins import LoginRequiredMixin
from apps.analytics.aggregators import (
    accuracy_metrics,
    coverage_heatmap, PRINCIPLES, JURISDICTIONS,
    PRINCIPLE_LABELS, JUR_LABELS,
    PRINCIPLE_TO_TOPICS, JURISDICTION_MAP,
)

_JURISDICTION_REVERSE = {v: k for k, v in JURISDICTION_MAP.items()}


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class HeatmapDataView(LoginRequiredMixin, View):
    def get(self, request):
        return JsonResponse(coverage_heatmap(user=request.user))


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class HeatmapPartialView(LoginRequiredMixin, View):
    def get(self, request):
        data       = coverage_heatmap(user=request.user)
        cell_index = {(c["principle"], c["jurisdiction"]): c for c in data["cells"]}

        rows = []
        for p in PRINCIPLES:
            row_cells = []
            for j in JURISDICTIONS:
                cell = dict(cell_index[(p, j)])
                cell["jur_label"]       = JUR_LABELS[j]
                cell["principle_label"] = PRINCIPLE_LABELS.get(p, p.replace("_", " ").title())
                row_cells.append(cell)
            rows.append({
                "principle": p,
                "label":     PRINCIPLE_LABELS.get(p, p.replace("_", " ").title()),
                "cells":     row_cells,
            })

        all_grey = all(c["status"] == "grey" for c in data["cells"])

        return render(request, "partials/_coverage_heatmap.html", {
            "rows":          rows,
            "jurisdictions": JURISDICTIONS,
            "all_grey":      all_grey,
        })


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class GapRegisterView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.mapping.models import Gap, MappingAnalysis
        jur_code  = request.GET.get("jurisdiction", "").upper()
        principle = request.GET.get("principle", "")

        gaps = (
            Gap.objects
            .filter(mapping__status=MappingAnalysis.APPROVED)
            .select_related(
                "obligation_mapping__regulation",
                "obligation_mapping__analysis",
            )
            .order_by("-priority", "-created_at")
        )

        # Analysts only see gaps in mapping analyses they themselves created.
        if get_user_role(request.user) == 'analyst':
            gaps = gaps.filter(mapping__created_by=request.user)

        if jur_code in _JURISDICTION_REVERSE:
            gaps = gaps.filter(
                obligation_mapping__regulation__jurisdiction=_JURISDICTION_REVERSE[jur_code]
            )
        if principle in PRINCIPLE_TO_TOPICS:
            gaps = gaps.filter(
                obligation_mapping__analysis__topic__in=PRINCIPLE_TO_TOPICS[principle]
            )

        return render(request, "partials/_gap_register.html", {
            "gaps":            gaps[:50],
            "jur_code":        jur_code,
            "jur_name":        JUR_LABELS.get(jur_code, ""),
            "principle":       principle,
            "principle_label": PRINCIPLE_LABELS.get(principle, ""),
            "filter_active":   bool(jur_code or principle),
        })


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class ConflictScannerView(LoginRequiredMixin, View):
    """GET /analytics/conflicts/ — surface every cross-jurisdiction conflict
    the comparison workflow has flagged. Reads from ComparisonResult where
    relationship='conflicting'. Grouped by jurisdiction pair so the analyst
    can see which two regimes disagree.

    No LLM call. Pure DB query over already-classified comparison rows.
    """

    def get(self, request):
        qs = ComparisonResult.objects.filter(
            relationship=ComparisonResult.CONFLICTING,
        ).select_related('run__reg_a', 'run__reg_b').order_by('-created_at')

        if get_user_role(request.user) == 'analyst':
            qs = qs.filter(run__created_by=request.user)

        # filter chips
        jur_filter = (request.GET.get('jur') or '').strip().lower()
        if jur_filter:
            qs = qs.filter(
                Q(run__reg_a__jurisdiction=jur_filter) | Q(run__reg_b__jurisdiction=jur_filter)
            )

        verified_only = request.GET.get('verified') == '1'
        if verified_only:
            qs = qs.filter(citation_verified=True)

        results = list(qs[:200])

        # group by jurisdiction-pair for the table sections
        from collections import OrderedDict
        groups = OrderedDict()
        for r in results:
            jur_a = (r.run.reg_a.jurisdiction if r.run.reg_a else '').capitalize()
            jur_b = (r.run.reg_b.jurisdiction if r.run.reg_b else '').capitalize()
            key = ' ↔ '.join(sorted([jur_a or '?', jur_b or '?']))
            groups.setdefault(key, []).append(r)

        # KPIs
        total = len(results)
        verified = sum(1 for r in results if r.citation_verified)
        high_risk = sum(1 for r in results if (r.hallucination_risk or 0) > 0.4)

        return render(request, 'pages/conflicts.html', {
            'groups':         groups,
            'total':          total,
            'verified':       verified,
            'high_risk':      high_risk,
            'jur_filter':     jur_filter,
            'verified_only':  verified_only,
            'jur_options': [
                ('',        'All jurisdiction pairs'),
                ('bahrain', 'Involving Bahrain'),
                ('india',   'Involving India'),
                ('kuwait',  'Involving Kuwait'),
            ],
        })


@method_decorator(role_required('analyst'), name='dispatch')
class CrossJurisdictionGapView(LoginRequiredMixin, View):
    """GET/POST /analytics/cross-gap/ — runs reasoning.workflows.generate_gap_analysis()
    against multiple jurisdictions on a free-text topic, returns a structured gap
    register with verbatim evidence + NLI hallucination scoring per row.

    This is the third reasoning workflow's UI entry point — comparison and mapping
    each have their own pages, gap analysis was previously only callable from
    Python. The result is rendered inline (no DB persistence) since each run is
    typically one-shot exploration.
    """

    JURISDICTION_OPTIONS = [
        ('Bahrain', 'Bahrain (PDPL)'),
        ('India',   'India (DPDPA)'),
        ('Kuwait',  'Kuwait (DPPR)'),
    ]

    def get(self, request):
        return render(request, 'pages/cross_gap_analysis.html', {
            'jurisdiction_options': self.JURISDICTION_OPTIONS,
            'report':               None,
            'topic':                '',
            'selected_jurisdictions': ['Bahrain', 'India', 'Kuwait'],
            'max_gaps':             10,
        })

    def post(self, request):
        topic = (request.POST.get('topic') or '').strip()
        jurs  = request.POST.getlist('jurisdictions') or ['Bahrain', 'India', 'Kuwait']
        try:
            max_gaps = int(request.POST.get('max_gaps', '10'))
        except (TypeError, ValueError):
            max_gaps = 10
        max_gaps = max(1, min(25, max_gaps))

        report = None
        error  = None
        if not topic or len(topic) < 3:
            error = 'Topic must be at least 3 characters.'
        else:
            try:
                from reasoning.workflows import generate_gap_analysis
                report = generate_gap_analysis(
                    topic=topic, jurisdictions=jurs,
                    top_k=4, max_gaps=max_gaps, rerank=True,
                )
                # audit trail — gap analysis is an admin-visible action
                try:
                    from apps.history.audit import log_event, Actions
                    log_event(
                        request.user,
                        getattr(Actions, 'GAP_ANALYSIS_RUN', 'analytics.gap_analysis'),
                        request=request,
                        description=f'Cross-jurisdiction gap analysis: {topic} ({", ".join(jurs)})',
                        metadata={
                            'topic':         topic,
                            'jurisdictions': jurs,
                            'gap_count':     len(report.gaps),
                        },
                    )
                except Exception:
                    pass
            except Exception as exc:
                import traceback
                traceback.print_exc()
                error = f'Analysis failed: {exc}'

        return render(request, 'pages/cross_gap_analysis.html', {
            'jurisdiction_options':   self.JURISDICTION_OPTIONS,
            'report':                 report,
            'topic':                  topic,
            'selected_jurisdictions': jurs,
            'max_gaps':               max_gaps,
            'error':                  error,
        })
