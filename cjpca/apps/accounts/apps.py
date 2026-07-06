from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'
    label = 'accounts'

    def ready(self):
        # Wire the post_save signal that auto-creates a UserProfile for every
        # new User. Imported here so Django's app registry is fully initialised
        # by the time the signal handlers are connected.
        from . import signals  # noqa: F401
