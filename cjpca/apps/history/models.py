from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Cross-cutting audit log.

    One row per security-relevant action. Used by /history/ for the user-
    facing timeline and as the system-of-record for compliance review.

    Field meanings:

    * ``event_type``   — action key, e.g. ``auth.login``, ``comparison.run``,
                          ``user.role_changed`` (see apps.history.audit
                          for the canonical list).
    * ``user``         — actor; nullable so failed-login attempts (no known
                          actor) and system-driven events can also be logged.
    * ``user_role_at_time`` — *snapshot* of the actor's RBAC role at the
                          moment the event happened. Read this directly when
                          rendering history; never look up the user's
                          current role, since roles change over time and we
                          want the historical record to stay accurate.
    * ``ip_address``   — request origin, extracted from X-Forwarded-For
                          (first hop) or REMOTE_ADDR.
    * ``description``  — pre-rendered human-readable line for display.
    * ``related_object_type`` / ``related_object_id`` — generic FK-style
                          pointer to whatever the action operated on
                          (a ComparisonRun, Document, User, etc).
    * ``change_detail`` — free-form JSON metadata (old/new values, file
                          paths, error messages, etc).
    """

    event_type          = models.CharField(max_length=50, db_index=True)
    user                = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                            on_delete=models.SET_NULL)
    user_role_at_time   = models.CharField(max_length=20, blank=True)
    ip_address          = models.GenericIPAddressField(null=True, blank=True)
    timestamp           = models.DateTimeField(auto_now_add=True, db_index=True)
    description         = models.CharField(max_length=500)
    related_object_type = models.CharField(max_length=50, blank=True)
    related_object_id   = models.PositiveIntegerField(null=True, blank=True)
    change_detail       = models.JSONField(default=dict)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['event_type', '-timestamp']),
        ]

    def __str__(self):
        return f'[{self.event_type}] {self.description}'
