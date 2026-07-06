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
    LOGIN          = 'auth.login'
    LOGIN_FAILED   = 'auth.login_failed'
    LOGOUT         = 'auth.logout'
    IDLE_TIMEOUT   = 'auth.idle_timeout'
    MFA_ENROLLED   = 'auth.mfa_enrolled'
    MFA_RESET      = 'auth.mfa_reset'
    AUTH_BACKUP_CODES_REGENERATED = 'auth.backup_codes_regenerated'
    SESSIONS_TERMINATED           = 'auth.sessions_terminated'
    # Analyst flows. Both the *initiation* (.run) and the eventual
    # *outcome* (.complete / .failed) are audited so BBK gets a full
    # trail per run for production compliance review. The complete/
    # failed events also serve as the trigger for in-app notifications
    # to the analyst who started the run (apps.notifications).
    COMPARISON_RUN      = 'comparison.run'
    COMPARISON_COMPLETE = 'comparison.complete'
    COMPARISON_FAILED   = 'comparison.failed'
    MAPPING_RUN         = 'mapping.run'
    MAPPING_COMPLETE    = 'mapping.complete'
    MAPPING_FAILED      = 'mapping.failed'
    # Reviewer flows
    REVIEW_SUBMIT  = 'review.submit'   # analyst sends a run to the reviewer queue
    REVIEW_ACCEPT  = 'review.accept'
    REVIEW_REJECT  = 'review.reject'
    REVIEW_MODIFY  = 'review.modify'
    # Admin / corpus
    DOCUMENT_UPLOAD     = 'document.upload'
    DOCUMENT_DELETE     = 'document.delete'
    INGESTION_COMPLETE  = 'ingestion.complete'
    INGESTION_FAILED    = 'ingestion.failed'
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
    USER_CREATED    = 'user.created'
    USER_ROLE_CHANGED = 'user.role_changed'
    USER_DISABLED     = 'user.disabled'
    USER_PASSWORD_RESET    = 'user.password_reset'
    USER_PASSWORD_CHANGED  = 'user.password_changed'

    @classmethod
    def all(cls) -> list:
        return [v for k, v in vars(cls).items()
                if not k.startswith('_') and isinstance(v, str)]


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
