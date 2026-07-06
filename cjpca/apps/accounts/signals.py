"""Account-related signal handlers.

* ``ensure_user_profile`` — auto-create a UserProfile for every new Django
  User. default role is ``analyst`` per spec; admins must be promoted
  explicitly.

The must_change_password flag is cleared in ForcedPasswordChangeView
(views.py) when the user successfully changes their password. doing it in
the view (rather than a post_save signal) avoids races with the admin
password-reset flow, which deliberately sets must_change_password=True
right after saving the user.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance, role=UserProfile.ANALYST)
    else:
        # Idempotent backfill: existing users predating this app get a
        # profile on their next save.
        UserProfile.objects.get_or_create(
            user=instance, defaults={'role': UserProfile.ANALYST},
        )
