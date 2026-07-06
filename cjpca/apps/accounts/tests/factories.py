"""Test helpers for building Users with a given role.

Kept tiny and dependency-free — we don't need factory_boy here.
"""

from django.contrib.auth import get_user_model

from apps.accounts.models import UserProfile


User = get_user_model()


def make_user(username='u', role=UserProfile.ANALYST, password='pw',
              with_mfa=True, **kwargs):
    """Create a User, set its role, and (by default) attach a confirmed TOTP
    device so ``ForceMFAEnrollmentMiddleware`` lets the request through.

    Pass ``with_mfa=False`` for tests that specifically want to assert the
    enrolment redirect.
    """
    user = User.objects.create_user(username=username, password=password, **kwargs)
    # post_save signal already created a profile defaulted to analyst
    profile = user.profile
    if profile.role != role:
        profile.role = role
        profile.save(update_fields=['role'])
    if with_mfa:
        try:
            from django_otp.plugins.otp_totp.models import TOTPDevice
            TOTPDevice.objects.get_or_create(
                user=user, name='test-device', defaults={'confirmed': True},
            )
        except ImportError:
            pass
    return user


def disconnect_stuck_run_hook():
    """Detach apps.comparison.apps.ComparisonConfig._reset_stuck_runs.

    The hook runs on the first ``request_started`` after process boot to clear
    stuck RUNNING comparison rows. In the test client it would fire on the
    first ``client.get``, then disconnect itself. Disconnecting up front
    avoids any test isolation surprises.
    """
    try:
        from django.apps import apps
        from django.core.signals import request_started
        cfg = apps.get_app_config('comparison')
        request_started.disconnect(cfg._reset_stuck_runs)
    except Exception:
        pass
