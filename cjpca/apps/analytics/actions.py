"""Unified Action Register construction.

Merges open policy-mapping gaps and unresolved clause conflicts into one
severity-ranked list for the Analytics dashboard, role-scoped identically.
"""
from django.urls import reverse

from apps.accounts.decorators import get_user_role
from apps.comparison.models import ComparisonResult
from apps.mapping.models import MappingAnalysis, Gap

_PRANK = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}


def _scoped_results(user):
    qs = ComparisonResult.objects.all()
    if not user or not user.is_authenticated:
        return qs.none()
    if get_user_role(user) == 'analyst':
        return qs.filter(run__created_by=user)
    return qs


def _scoped_mappings(user):
    qs = MappingAnalysis.objects.filter(status__in=[
        MappingAnalysis.COMPLETE, MappingAnalysis.REVIEW, MappingAnalysis.APPROVED,
    ])
    if user and user.is_authenticated and get_user_role(user) == 'analyst':
        qs = qs.filter(created_by=user)
    return qs


def build_action_register(user):
    """Return the severity-ranked list of open gaps + unresolved conflicts."""
    items = []

    gap_qs = (
        Gap.objects.filter(mapping__in=_scoped_mappings(user), closed_at__isnull=True)
        .select_related('obligation_mapping', 'obligation_mapping__regulation',
                        'mapping', 'mapping__policy_doc')
        .order_by('-mapping__completed_at')[:80]
    )
    for g in gap_qs:
        om = g.obligation_mapping
        reg = om.regulation if om else None
        try:
            url = reverse('mapping-workspace', args=[g.mapping.pk]) if g.mapping_id else ''
        except Exception:
            url = ''
        items.append({
            'kind': 'gap', 'kind_label': 'Policy gap',
            'priority': g.priority or 'medium', 'rank': _PRANK.get(g.priority, 2),
            'title': (om.obligation_title if om else '') or 'Obligation gap',
            'jurisdiction': (reg.jurisdiction.capitalize() if reg and reg.jurisdiction else '—'),
            'source': (om.article_ref if om else ''),
            'context': (g.mapping.policy_doc.name if g.mapping and g.mapping.policy_doc else ''),
            'status': 'Open', 'confidence': None, 'url': url,
        })

    conf_qs = (
        _scoped_results(user)
        .filter(relationship=ComparisonResult.CONFLICTING)
        .exclude(lifecycle=ComparisonResult.APPROVED)
        .select_related('run', 'run__reg_a', 'run__reg_b')
        .order_by('-confidence')[:80]
    )
    for r in conf_qs:
        try:
            url = reverse('comparison-workspace', args=[r.run.pk]) if r.run_id else ''
        except Exception:
            url = ''
        items.append({
            'kind': 'conflict', 'kind_label': 'Clause conflict',
            'priority': 'high', 'rank': 1,
            'title': (r.key_difference or f'{r.citation_a} vs {r.citation_b or "—"}')[:160],
            'jurisdiction': (r.run.pair_key.upper() if r.run else '—'),
            'source': (f'{r.citation_a} ↔ {r.citation_b}' if r.citation_b else r.citation_a),
            'context': 'Cross-regulation conflict',
            'status': (r.lifecycle.capitalize() if r.lifecycle else 'Draft'),
            'confidence': r.confidence_pct, 'url': url,
        })

    items.sort(key=lambda a: (a['rank'], -(a['confidence'] or 0)))
    return items
