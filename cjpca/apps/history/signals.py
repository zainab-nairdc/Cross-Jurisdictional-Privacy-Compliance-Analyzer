"""Signal handlers that auto-log auth + MFA events to AuditLog.

Connects:
* django.contrib.auth.signals.user_logged_in     → auth.login
* django.contrib.auth.signals.user_logged_out    → auth.logout
* django.contrib.auth.signals.user_login_failed  → auth.login_failed
* django_otp.plugins.otp_totp.models.TOTPDevice  → auth.mfa_enrolled
  (post_save with confirmed=True, captures both wizard enrolment and
   admin-created devices)

For events not driven by signals (comparison.run, document.upload,
user.role_changed, etc.) the relevant view calls ``audit.log_event``
directly.

Two caveats worth knowing before you trust this file:

* The TOTPDevice receiver below is wrapped in ``try/except ImportError``
  and django_otp is **not** in INSTALLED_APPS any more, so it never
  registers and ``auth.mfa_enrolled`` is never written.
* ``auth.idle_timeout`` used to be logged from an
  ``IdleSessionTimeoutMiddleware``. That middleware no longer exists and
  nothing replaced it, so that key is dormant too.

Both are recorded in ``apps.history.audit.NOT_EMITTED``, which the test
suite pins.
"""

from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed,
)
from django.dispatch import receiver

from .audit import log_event, Actions


# Track the previous-confirmed state of TOTP devices on the per-instance level
# so post_save handlers fire only on the False→True transition (i.e. actual
# enrolment), not on every save of an already-confirmed device.
@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    log_event(
        user, Actions.LOGIN,
        request=request,
        description=f'{user.username} signed in',
    )


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    if user is None:
        return
    log_event(
        user, Actions.LOGOUT,
        request=request,
        description=f'{user.username} signed out',
    )


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    # `credentials` is dict-like; password is stripped by Django before this
    # signal fires, but be defensive and only persist the username.
    attempted = (credentials or {}).get('username') or ''
    log_event(
        None, Actions.LOGIN_FAILED,
        request=request,
        description=f'Failed login attempt for "{attempted}"' if attempted else 'Failed login attempt',
        metadata={'attempted_username': attempted[:100]},
    )


# ── MFA enrollment ───────────────────────────────────────────────────────────
# Hook TOTPDevice post_save and emit auth.mfa_enrolled the first time a device
# transitions to confirmed=True. Importing inside a try/except so test
# environments without django_otp installed (shouldn't happen post-Part-B)
# still load this module.
try:
    from django.db.models.signals import post_save
    from django_otp.plugins.otp_totp.models import TOTPDevice

    @receiver(post_save, sender=TOTPDevice)
    def _on_totp_device_saved(sender, instance, created, **kwargs):
        if not instance.confirmed:
            return
        # We can't easily detect first-time enrollment vs subsequent saves
        # of an already-confirmed device. Heuristic: only log on creation,
        # since two_factor's setup wizard creates a device with confirmed=
        # True only at the moment of successful TOTP validation.
        if not created:
            return
        log_event(
            instance.user, Actions.MFA_ENROLLED,
            target_type='otp_totp.TOTPDevice',
            target_id=instance.pk,
            description=f'{instance.user.username} enrolled MFA',
        )
except ImportError:  # pragma: no cover
    pass
