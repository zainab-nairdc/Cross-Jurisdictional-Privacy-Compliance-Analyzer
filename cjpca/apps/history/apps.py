from django.apps import AppConfig


class HistoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.history'
    label = 'history'

    def ready(self):
        # Connect auth + MFA signal handlers that write to AuditLog.
        from . import signals  # noqa: F401
