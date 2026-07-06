from django.apps import AppConfig


class MappingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.mapping'
    label = 'mapping'

    def ready(self):
        # Defer DB access to the first HTTP request so it doesn't fire during
        # test discovery or management commands (avoids RuntimeWarning).
        from django.core.signals import request_started
        request_started.connect(self._reset_stuck_analyses)

    def _reset_stuck_analyses(self, sender, **kwargs):
        from django.core.signals import request_started
        request_started.disconnect(self._reset_stuck_analyses)
        try:
            from datetime import timedelta
            from django.utils import timezone
            from apps.mapping.models import MappingAnalysis
            cutoff = timezone.now() - timedelta(seconds=90)
            MappingAnalysis.objects.filter(
                status=MappingAnalysis.RUNNING,
                created_at__lt=cutoff,
            ).update(
                status=MappingAnalysis.FAILED,
                error='Server restarted — analysis did not complete. Please try again.',
            )
        except Exception:
            pass
