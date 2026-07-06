"""Home dashboards — role-aware landing pages.

Each role gets its own template and its own context:

* analyst  -> pages/home_analyst.html  — their own runs/mappings + start-new tiles
* reviewer -> pages/home_reviewer.html — review queue, submitted handoffs, decisions
* admin    -> pages/home_admin.html    — system health, ingestion, users, system events

`HomeView` resolves the role from the user's profile, picks the matching
template, and supplies a context tuned to what that role does day-to-day.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.decorators import RoleRequiredMixin, get_user_role
from apps.library.models import Document
from apps.ingestion.models import IngestionJob, QuarantinedChunk
from apps.comparison.models import ComparisonResult, ComparisonRun
from apps.mapping.models import MappingAnalysis, ObligationMapping, Gap
from apps.history.models import AuditLog

_RING_CIRCUMFERENCE = round(2 * math.pi * 36, 2)


def _greeting() -> str:
    h = datetime.now().hour
    if h < 12:  return 'Good morning'
    if h < 17:  return 'Good afternoon'
    return 'Good evening'


def _coverage_pct() -> tuple[int, int, int]:
    total = ObligationMapping.objects.count()
    covered = ObligationMapping.objects.filter(coverage=ObligationMapping.COVERED).count()
    return (
        round(covered / total * 100) if total else 0,
        covered,
        total,
    )


def _coverage_by_jurisdiction() -> dict:
    jur_map = [
        (Document.BAHRAIN, 'Bahrain'),
        (Document.KUWAIT,  'Kuwait'),
        (Document.INDIA,   'India'),
    ]
    labels, values = [], []
    for code, label in jur_map:
        regs = Document.objects.filter(
            doc_type=Document.REGULATION, jurisdiction=code, status=Document.INDEXED,
        )
        t = ObligationMapping.objects.filter(regulation__in=regs).count()
        c = ObligationMapping.objects.filter(
            regulation__in=regs, coverage=ObligationMapping.COVERED,
        ).count()
        labels.append(label)
        values.append(round(c / t * 100) if t else 0)
    return {'labels': labels, 'values': values}


class HomeView(RoleRequiredMixin, TemplateView):
    """GET / — landing page. Dispatches to a per-role template + context."""
    allowed_roles = ('analyst', 'reviewer', 'admin')

    def get_template_names(self):
        role = get_user_role(self.request.user) or 'analyst'
        return [f'pages/home_{role}.html', 'pages/home.html']

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        role = get_user_role(self.request.user) or 'analyst'
        ctx['greeting']  = _greeting()
        ctx['user_role'] = role
        if role == 'analyst':
            ctx.update(_analyst_ctx(self.request.user))
        elif role == 'reviewer':
            ctx.update(_reviewer_ctx(self.request.user))
        elif role == 'admin':
            ctx.update(_admin_ctx(self.request.user))
        return ctx


def _analyst_ctx(user) -> dict:
    """Context for the analyst dashboard — focused on the user's own runs."""
    coverage_pct, covered, total = _coverage_pct()
    score_offset = round(_RING_CIRCUMFERENCE * (1 - coverage_pct / 100), 2)

    my_runs_qs = ComparisonRun.objects.filter(created_by=user)
    my_maps_qs = MappingAnalysis.objects.filter(created_by=user)

    my_runs = list(
        my_runs_qs.select_related('reg_a', 'reg_b').order_by('-created_at')[:5]
    )
    my_mappings = list(
        my_maps_qs.select_related('policy_doc').order_by('-run_at')[:5]
    )

    my_open_gaps = Gap.objects.filter(mapping__created_by=user).count()
    my_high_gaps = Gap.objects.filter(
        mapping__created_by=user, priority=Gap.HIGH,
    ).count()
    my_submitted = my_runs_qs.filter(submitted_for_review_at__isnull=False).count()

    return {
        'my_runs':              my_runs,
        'my_mappings':          my_mappings,
        'my_runs_total':        my_runs_qs.count(),
        'my_mappings_total':    my_maps_qs.count(),
        'my_open_gaps':         my_open_gaps,
        'my_high_gaps':         my_high_gaps,
        'my_submitted':         my_submitted,
        'coverage_pct':         coverage_pct,
        'coverage_covered':     covered,
        'coverage_total':       total,
        'score_offset':         score_offset,
        'score_circumference':  _RING_CIRCUMFERENCE,
        'chart_data_json':      json.dumps({
            'coverageByJurisdiction': _coverage_by_jurisdiction(),
        }),
    }


def _reviewer_ctx(user) -> dict:
    """Context for the reviewer dashboard — focused on the review queue."""
    submitted_runs = list(
        ComparisonRun.objects
        .filter(submitted_for_review_at__isnull=False)
        .select_related('reg_a', 'reg_b', 'submitted_by')
        .order_by('-submitted_for_review_at')[:6]
    )

    pending_review = ComparisonResult.objects.filter(lifecycle='draft').count()
    approved_total = ComparisonResult.objects.filter(lifecycle='approved').count()
    rejected_total = ComparisonResult.objects.filter(lifecycle='rejected').count()
    reviewed_total = approved_total + rejected_total

    mapping_review_queue = list(
        MappingAnalysis.objects
        .filter(Q(status=MappingAnalysis.REVIEW) | Q(gap_count__gt=0))
        .select_related('policy_doc')
        .order_by('-run_at')[:5]
    )

    # Work-event audit feed: only comparison/mapping/review actions, last 8.
    work_actions = [
        'comparison.run', 'comparison.complete', 'comparison.failed',
        'mapping.run', 'mapping.complete', 'mapping.failed',
        'review.submit', 'review.accept', 'review.reject', 'review.modify',
    ]
    recent_events = list(
        AuditLog.objects
        .filter(event_type__in=work_actions)
        .select_related('user')
        .order_by('-timestamp')[:8]
    )

    return {
        'pending_review':       pending_review,
        'reviewed_total':       reviewed_total,
        'approved_total':       approved_total,
        'rejected_total':       rejected_total,
        'submitted_runs':       submitted_runs,
        'mapping_review_queue': mapping_review_queue,
        'recent_events':        recent_events,
    }


def _admin_ctx(user) -> dict:
    """Context for the admin dashboard — focused on system health."""
    User = get_user_model()
    now = timezone.now()
    last_24h = now - timedelta(hours=24)

    jobs_active = list(
        IngestionJob.objects
        .filter(status__in=[IngestionJob.QUEUED, IngestionJob.RUNNING])
        .select_related('document')[:6]
    )

    # System-event audit feed: auth / document / user / quarantine / reasoning.
    system_actions = [
        'auth.login', 'auth.login_failed', 'auth.logout', 'auth.idle_timeout',
        'auth.mfa_enrolled', 'auth.mfa_reset',
        'document.upload', 'document.delete',
        'ingestion.complete', 'ingestion.failed',
        'quarantine.flagged', 'quarantine.approved', 'quarantine.rejected',
        'reasoning.validation_error',
        'user.created', 'user.role_changed', 'user.disabled',
        'user.password_reset', 'user.password_changed',
    ]
    recent_events = list(
        AuditLog.objects
        .filter(event_type__in=system_actions)
        .select_related('user')
        .order_by('-timestamp')[:10]
    )

    return {
        'docs_total':       Document.objects.count(),
        'docs_indexed':     Document.objects.filter(status=Document.INDEXED).count(),
        'docs_processing':  Document.objects.filter(status=Document.PROCESSING).count(),
        'docs_failed':      Document.objects.filter(status=Document.FAILED).count(),
        'jobs_active':      jobs_active,
        'jobs_active_count': len(jobs_active),
        'jobs_failed_24h':  IngestionJob.objects.filter(
                                status=IngestionJob.FAILED,
                                updated_at__gte=last_24h,
                            ).count(),
        'quarantine_pending': QuarantinedChunk.objects.filter(
                                status=QuarantinedChunk.PENDING,
                              ).count(),
        'users_total':      User.objects.filter(is_active=True).count(),
        'users_by_role':    {
            role: User.objects.filter(profile__role=role, is_active=True).count()
            for role in ('analyst', 'reviewer', 'admin')
        },
        'recent_events':    recent_events,
    }
