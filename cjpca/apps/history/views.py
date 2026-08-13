"""History timeline — fed by apps.history.AuditLog as the system of record.

Per-role scoping:

* admin    — sees every event (system + work)
* reviewer — work-only slice (comparison/mapping/review/export/analytics);
             auth, document, user-management and quarantine events are
             hidden because they belong to the admin oversight surface
* analyst  — only their own actions (work events they generated)

The view filters AuditLog rows by category before rendering, so the
template (``pages/history.html``) is unchanged.
"""

from itertools import groupby

from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from apps.accounts.decorators import role_required, get_user_role
from apps.comparison.models import ComparisonRun
from apps.library.models import Document
from apps.mapping.models import MappingAnalysis

from .models import AuditLog

ALL_ROLES = ('admin', 'reviewer', 'analyst')

# Categories visible to each role. Admin gets the full set, reviewer is
# limited to work events, analyst sees only their own actions (which the
# query then narrows by user= and category isn't restricted further).
#
# 'export' and 'analytics' belong in the work set: an analyst who downloads
# an approved package or runs a gap analysis must be able to see that in
# their own timeline. Before, both fell through _action_category()'s
# fallback into 'auth' and were filtered out of every non-admin view.
WORK_CATEGORIES = {'comparison', 'mapping', 'review', 'export', 'analytics'}
ADMIN_CATEGORIES = {'auth', 'comparison', 'mapping', 'review', 'upload',
                    'admin', 'export', 'analytics', 'system'}


def _role_category_filter(role: str) -> set | None:
    if role == 'admin':
        return None  # no filter — sees everything
    if role == 'reviewer':
        return WORK_CATEGORIES
    return WORK_CATEGORIES  # analyst gets work events too, but scoped to self


# Display metadata per category — controls badge colour, label.
# BBK brand palette only: navy (#002583) for system/security events, orange
# (from the logo, deepened to #C2410C for text contrast) for work/action events.
# BBK logo palette: deep blue for system/security events, orange for work
# events. (Gold removed by request.) White text on both.
_BLUE   = {'color': '#FFFFFF', 'bg': '#121676'}
_ORANGE = {'color': '#FFFFFF', 'bg': '#F79A2E'}
EVENT_META = {
    'auth':        {'label': 'Auth',       **_BLUE},
    'comparison':  {'label': 'Comparison', **_BLUE},
    'admin':       {'label': 'Admin',      **_BLUE},
    'system':      {'label': 'System',     **_BLUE},
    'mapping':     {'label': 'Mapping',    **_ORANGE},
    'upload':      {'label': 'Upload',     **_ORANGE},
    'review':      {'label': 'Review',     **_ORANGE},
    'export':      {'label': 'Export',     **_ORANGE},
    'analytics':   {'label': 'Analytics',  **_ORANGE},
}


# Maps an action key (event_type) to the category bucket used by the
# template's filter chips.
#
# Keep this exhaustive. The old version matched a prefix of 'export.' while
# the export views actually emit 'exports.downloaded' — so the Export chip
# never matched anything — and everything unmatched fell into an 'auth'
# fallback. That silently mislabelled ingestion, quarantine, settings and
# document-tag rows as "Auth", and, because non-admins are filtered to
# WORK_CATEGORIES, dropped them from reviewer and analyst timelines
# altogether. Unknown keys now land in 'system' (admin-visible) so a new
# event type is merely uncategorised rather than invisible.
_CATEGORY_PREFIXES = (
    ('auth.',       'auth'),
    ('comparison.', 'comparison'),
    ('mapping.',    'mapping'),
    ('review.',     'review'),
    ('document.',   'upload'),
    ('library.',    'upload'),
    ('doc.',        'upload'),
    ('user.',       'admin'),
    ('settings.',   'admin'),
    ('exports.',    'export'),
    ('export.',     'export'),
    ('analytics.',  'analytics'),
    ('ingestion.',  'system'),
    ('quarantine.', 'system'),
    ('reasoning.',  'system'),
    ('geofence.',   'system'),
)


def _action_category(action: str) -> str:
    for prefix, category in _CATEGORY_PREFIXES:
        if action.startswith(prefix):
            return category
    return 'system'  # unknown keys stay visible to admins


class _Event:
    __slots__ = ('pk', 'etype', 'category', 'meta', 'description',
                 'timestamp', 'user_label', 'detail')

    def __init__(self, pk, etype, category, description, timestamp,
                 user_label='System', detail=None):
        self.pk          = pk
        self.etype       = etype
        self.category    = category
        self.meta        = EVENT_META.get(category, EVENT_META['auth'])
        self.description = description
        self.timestamp   = timestamp
        self.user_label  = user_label
        self.detail      = detail or {}


def _build_events(user=None, scope_to_user=False, category_filter=None, limit=500):
    """Build the timeline from AuditLog rows.

    :param scope_to_user: restrict to rows where the actor is this user
                          (analyst self-view).
    :param category_filter: optional set of category strings to keep
                            (e.g. ``{'comparison', 'mapping', 'review'}``
                            for the reviewer slice). ``None`` means no
                            category restriction (admin sees everything).
    """
    qs = AuditLog.objects.select_related('user').order_by('-timestamp')
    if scope_to_user and user is not None:
        qs = qs.filter(user=user)

    events = []
    for row in qs[:limit]:
        category = _action_category(row.event_type)
        if category_filter is not None and category not in category_filter:
            continue
        if row.user is not None:
            user_label = row.user.get_full_name() or row.user.username
        elif row.event_type.startswith('geofence.'):
            user_label = 'Unknown'
        else:
            user_label = 'System'

        events.append(_Event(
            pk=f'al_{row.pk}',
            etype=row.event_type,
            category=category,
            description=row.description,
            timestamp=row.timestamp,
            user_label=user_label,
            detail={
                'action':            row.event_type,
                'role_at_time':      row.user_role_at_time,
                'ip':                row.ip_address,
                'target_type':       row.related_object_type,
                'target_id':         row.related_object_id,
                'metadata':          row.change_detail or {},
            },
        ))
    return events


def _apply_filters(events, request):
    q           = request.GET.get('q', '').strip().lower()
    type_filter = request.GET.get('type', '')
    date_from   = request.GET.get('date_from', '')
    date_to     = request.GET.get('date_to', '')

    if q:
        events = [e for e in events if q in e.description.lower() or q in e.user_label.lower()]

    if type_filter and type_filter != 'all':
        cat_map = {
            'comparisons': 'comparison',
            'reviews':     'review',
            'uploads':     'upload',
            'mappings':    'mapping',
            'auth':        'auth',
            'admin':       'admin',
            'exports':     'export',
            'analytics':   'analytics',
            'system':      'system',
        }
        cat = cat_map.get(type_filter.lower())
        if cat:
            events = [e for e in events if e.category == cat]

    if date_from:
        try:
            from datetime import date as _date
            df = _date.fromisoformat(date_from)
            events = [e for e in events if timezone.localtime(e.timestamp).date() >= df]
        except (ValueError, Exception):
            pass

    if date_to:
        try:
            from datetime import date as _date
            dt = _date.fromisoformat(date_to)
            events = [e for e in events if timezone.localtime(e.timestamp).date() <= dt]
        except (ValueError, Exception):
            pass

    return events


@method_decorator(role_required('admin'), name='dispatch')
class HistoryView(View):
    """GET /history/ — admin-only history & audit log.

    Previously open to all roles with per-role row scoping (analyst saw
    their own actions, reviewer saw work events). Locked down to admin
    by request — analysts and reviewers no longer have a self-audit view.
    """

    def get(self, request):
        role = get_user_role(request.user) or 'analyst'
        cat_filter    = _role_category_filter(role)
        scope_to_user = (role == 'analyst')

        all_events = _build_events(
            user=request.user,
            scope_to_user=scope_to_user,
            category_filter=cat_filter,
        )
        filtered_events = _apply_filters(all_events, request)[:300]

        def date_key(e):
            return timezone.localtime(e.timestamp).date()

        grouped = [(d, list(g)) for d, g in groupby(filtered_events, key=date_key)]

        # Stats reflect what this role can see — counts the rows in scope.
        scoped_qs = AuditLog.objects.all()
        if scope_to_user:
            scoped_qs = scoped_qs.filter(user=request.user)

        stats = {
            'total_events':  scoped_qs.count(),
            'analyses':      ComparisonRun.objects.count() + MappingAnalysis.objects.count(),
            'uploads':       Document.objects.count() if role == 'admin' else 0,
            'gaps_found':    sum(ma.gap_count for ma in MappingAnalysis.objects.only('gap_count')),
            'gaps_resolved': 0,
        }

        ctx = {
            'grouped_events': grouped,
            'total_filtered': len(filtered_events),
            'stats':          stats,
            'q':              request.GET.get('q', ''),
            'type_filter':    request.GET.get('type', ''),
            'user_filter':    request.GET.get('user', ''),
            'date_from':      request.GET.get('date_from', ''),
            'date_to':        request.GET.get('date_to', ''),
            'history_scope':  role,
        }

        if request.headers.get('HX-Request'):
            return render(request, 'partials/_history_list.html', ctx)

        return render(request, 'pages/history.html', ctx)


@method_decorator(role_required('admin'), name='dispatch')
class EventDetailView(View):
    """GET /history/<slug:pk>/ — admin-only event detail fragment."""

    def get(self, request, pk):
        role = get_user_role(request.user) or 'analyst'
        all_events = _build_events(
            user=request.user,
            scope_to_user=(role == 'analyst'),
            category_filter=_role_category_filter(role),
        )
        event = next((e for e in all_events if e.pk == pk), None)
        if event is None:
            from django.http import Http404
            raise Http404

        return render(request, 'partials/_history_event_detail.html', {'event': event})
