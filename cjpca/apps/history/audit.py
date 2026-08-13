"""Cross-cutting audit log helpers.

The single public entry point is ``log_event(...)``. Use it from views,
signal handlers, middleware — anywhere a security-relevant action happens.

::

    from apps.history.audit import log_event
    log_event(
        request.user, 'comparison.run',
        request=request,
        target_type='comparison.ComparisonRun', target_id=run.pk,
        metadata={'pair_key': run.pair_key, 'topics': run.topics},
        description=f'Ran comparison {run.reg_a.name} vs {run.reg_b.name}',
    )

Two design choices that matter:

1. The user's role is **snapshotted at call time** (read from
   ``user.profile.role``) and stored in ``user_role_at_time``. Never look
   the role up at render time — roles change, and we want the audit record
   to reflect what was true *when the action happened*.
2. The function is best-effort: if anything goes wrong (DB outage, missing
   profile, etc.) it logs at warning level and returns ``None`` rather
   than raising. Audit logging must never break the actual business flow.
"""

import logging
from typing import Optional

from django.http import HttpRequest

from .models import AuditLog


log = logging.getLogger(__name__)


# Canonical action keys recognised by the system. Defined here so callers
# can reference constants and tests can iterate them. Keep alphabetical
# inside each section.
class Actions:
    # Authentication / session
    #
    # NOTE on the dormant keys below. MFA, the idle-timeout middleware and
    # the user-management screens were pulled out of the PoC (see the
    # comment at the top of apps/accounts/urls.py). Their constants are
    # kept because SECURITY_RBAC_README part D2 enumerates them and the
    # history/monitoring surfaces are built against that list — but nothing
    # currently emits them. ``NOT_EMITTED`` below is the authoritative
    # record of which ones those are; the test suite asserts that set is
    # exactly right, so re-adding a feature and forgetting to re-wire its
    # audit call fails loudly instead of silently.
    LOGIN          = 'auth.login'
    LOGIN_FAILED   = 'auth.login_failed'
    LOGOUT         = 'auth.logout'
    IDLE_TIMEOUT   = 'auth.idle_timeout'      # dormant: no idle middleware
    MFA_ENROLLED   = 'auth.mfa_enrolled'      # dormant: django_otp removed
    MFA_RESET      = 'auth.mfa_reset'         # dormant: no route
    AUTH_BACKUP_CODES_REGENERATED = 'auth.backup_codes_regenerated'  # dormant: no route
    SESSIONS_TERMINATED           = 'auth.sessions_terminated'
    # Analyst flows. Both the *initiation* (.run) and the eventual
    # *outcome* (.complete / .failed) are audited so BBK gets a full
    # trail per run for production compliance review. The complete/
    # failed events also serve as the trigger for in-app notifications
    # to the analyst who started the run (apps.notifications).
    COMPARISON_RUN      = 'comparison.run'
    COMPARISON_COMPLETE = 'comparison.complete'
    COMPARISON_FAILED   = 'comparison.failed'
    # Reuse of an approved assessment instead of a fresh comparison. All three
    # are emitted from apps.comparison.views.RunComparisonView: the offer is
    # recorded as well as the decision, so the trail shows what the analyst was
    # shown, not only what they chose.
    COMPARISON_REUSE_OFFERED  = 'comparison.reuse_offered'
    COMPARISON_REUSE_ACCEPTED = 'comparison.reuse_accepted'
    COMPARISON_RERUN_FORCED   = 'comparison.rerun_forced'
    MAPPING_RUN         = 'mapping.run'
    MAPPING_COMPLETE    = 'mapping.complete'
    MAPPING_FAILED      = 'mapping.failed'
    # Reviewer flows
    REVIEW_SUBMIT  = 'review.submit'   # analyst sends a run to the reviewer queue
    REVIEW_ACCEPT  = 'review.accept'
    REVIEW_REJECT  = 'review.reject'
    REVIEW_MODIFY  = 'review.modify'
    # Approved-package exports. Emitted by the per-run/per-analysis export
    # views AND by the bulk reviewer export at /review/export/<format>/.
    EXPORT_DOWNLOADED = 'exports.downloaded'
    # Admin / corpus
    DOCUMENT_UPLOAD     = 'document.upload'
    DOCUMENT_DELETE     = 'document.delete'
    DOCUMENT_TAG        = 'library.document_tag'
    DOC_SUPERSEDED      = 'doc.superseded'
    INGESTION_COMPLETE  = 'ingestion.complete'
    INGESTION_FAILED    = 'ingestion.failed'
    # Cross-jurisdiction gap analysis (analytics page)
    GAP_ANALYSIS_RUN    = 'analytics.gap_analysis'
    # Admin-configurable site settings (jurisdiction display mode, etc.)
    SETTINGS_UPDATED    = 'settings.updated'
    # Reasoning layer — surfaced on the system monitoring page so admins
    # can see when the LLM is producing output that even OutputFixingParser
    # cannot rescue. One row per failed parse-after-retry.
    REASONING_VALIDATION_ERROR = 'reasoning.validation_error'
    # Prompt-injection scanner — the inline defense at ingest time. Every
    # detection writes a QUARANTINE_FLAGGED row; every admin decision in the
    # quarantine queue writes APPROVED or REJECTED. This trail is what lets
    # the thesis claim defense-in-depth: detection is auditable, not silent.
    QUARANTINE_FLAGGED   = 'quarantine.flagged'
    QUARANTINE_APPROVED  = 'quarantine.approved'
    QUARANTINE_REJECTED  = 'quarantine.rejected'
    # User management — all dormant: the views in apps/accounts/views.py
    # carry working log_event calls but nothing routes them (see
    # apps/accounts/urls.py).
    USER_CREATED    = 'user.created'
    USER_ROLE_CHANGED = 'user.role_changed'
    USER_DISABLED     = 'user.disabled'
    USER_PASSWORD_RESET    = 'user.password_reset'
    USER_PASSWORD_CHANGED  = 'user.password_changed'

    @classmethod
    def all(cls) -> list:
        return [v for k, v in vars(cls).items()
                if not k.startswith('_') and isinstance(v, str)]


# ── Dormant actions ──────────────────────────────────────────────────────────
# Declaring a constant is not the same as writing rows, and the two drifted
# badly enough once that whole categories of activity were going unrecorded
# while the dashboards implied otherwise. These two sets are the honest
# record of the gap, and ``apps.accounts.tests.test_audit.ActionEmissionTests``
# pins them: it walks the source with the AST looking for the action passed
# to a ``log_event(...)`` call, so an action can neither lose its call site
# nor quietly gain one without a test failing.

#: No code anywhere calls ``log_event`` with these. They are referenced only
#: by *readers* (dashboard queries), which is why the corresponding panels
#: always render zero.
NO_CALL_SITE = {
    # SESSION_IDLE_TIMEOUT is configured and the login page still handles
    # ?reason=idle, but the IdleSessionTimeoutMiddleware that used to emit
    # this was removed and is not in settings.MIDDLEWARE.
    Actions.IDLE_TIMEOUT,
    # apps.accounts.views.SystemMonitoringView *queries* this event type in
    # four places; nothing writes it. Wiring it up means calling log_event
    # from the OutputFixingParser give-up path in reasoning/.
    Actions.REASONING_VALIDATION_ERROR,
}

#: A ``log_event`` call site exists and is correct, but nothing can reach it.
#: Restoring the feature restores the audit row — no audit work needed.
UNREACHABLE = {
    # The receiver in apps.history.signals sits inside a try/ImportError and
    # django_otp is no longer in INSTALLED_APPS, so it never registers.
    Actions.MFA_ENROLLED,
    # These live in apps/accounts/views.py, but apps/accounts/urls.py routes
    # only logout/ and monitoring/ — the views have no URL.
    Actions.MFA_RESET,
    Actions.AUTH_BACKUP_CODES_REGENERATED,
    Actions.USER_CREATED,
    Actions.USER_ROLE_CHANGED,
    Actions.USER_DISABLED,
    Actions.USER_PASSWORD_RESET,
    Actions.USER_PASSWORD_CHANGED,
    # Emitted by apps.accounts.session_utils.force_logout_user, whose only
    # callers are the unrouted user-management views above.
    Actions.SESSIONS_TERMINATED,
}

#: Everything that cannot appear in the audit log today, for either reason.
NOT_EMITTED = NO_CALL_SITE | UNREACHABLE


def _extract_ip(request: Optional[HttpRequest]) -> Optional[str]:
    """Return the originating IP, honouring X-Forwarded-For if present.

    XFF can contain a comma-separated chain (client, proxy1, proxy2). The
    *first* hop is the original client. We don't validate it (anyone can
    spoof XFF) — for trusted-proxy setups, configure SECURE_PROXY_SSL_HEADER
    and friends at the deploy layer.
    """
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        client_ip = xff.split(',')[0].strip()
        if client_ip:
            return client_ip
    return request.META.get('REMOTE_ADDR') or None


def _snapshot_role(user) -> str:
    """Return the user's role string at this moment, or '' if unknown."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return ''
    profile = getattr(user, 'profile', None)
    if profile is None:
        return ''
    return profile.role or ''


def log_event(
    user,
    action: str,
    *,
    request: Optional[HttpRequest] = None,
    target_type: str = '',
    target_id: Optional[int] = None,
    description: str = '',
    metadata: Optional[dict] = None,
) -> Optional[AuditLog]:
    """Write a single audit row. Returns the created row, or None on error.

    :param user:        actor (or None for anonymous events like failed
                        login attempts)
    :param action:      action key — use one of ``Actions.*`` constants
    :param request:     HttpRequest, used to extract IP. Optional.
    :param target_type: dotted "app.Model" pointer to the affected object
                        (e.g. ``'comparison.ComparisonRun'``)
    :param target_id:   PK of the affected object (or None)
    :param description: pre-rendered display string. If blank, defaults to
                        ``f'{action} by {username}'``.
    :param metadata:    arbitrary JSON-serializable dict
    """
    try:
        username = (
            user.username if user is not None and getattr(user, 'is_authenticated', False)
            else 'anonymous'
        )
        # Cap target_id at the model's PositiveIntegerField bound — anything
        # bigger is clearly junk and would 500 the insert.
        try:
            target_pk = int(target_id) if target_id is not None else None
        except (TypeError, ValueError):
            target_pk = None
        if target_pk is not None and target_pk < 0:
            target_pk = None

        return AuditLog.objects.create(
            event_type=action,
            user=user if user is not None and getattr(user, 'is_authenticated', False) else None,
            user_role_at_time=_snapshot_role(user),
            ip_address=_extract_ip(request),
            description=description or f'{action} by {username}',
            related_object_type=target_type,
            related_object_id=target_pk,
            change_detail=metadata or {},
        )
    except Exception as exc:  # pragma: no cover — defensive
        log.warning(
            'audit.log_event failed: action=%s user=%s err=%s',
            action, getattr(user, 'username', None), exc,
        )
        return None
