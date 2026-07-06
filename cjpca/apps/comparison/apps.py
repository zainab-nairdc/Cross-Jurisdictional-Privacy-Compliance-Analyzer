from django.apps import AppConfig


class ComparisonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.comparison'
    label = 'comparison'

    def ready(self):
        # Defer the stuck-run reset to the first HTTP request so it doesn't
        # fire during test discovery or management commands (avoids the
        # "Accessing the database during app initialization" RuntimeWarning).
        from django.core.signals import request_started
        request_started.connect(self._reset_stuck_runs)

    def _reset_stuck_runs(self, sender, **kwargs):
        from django.core.signals import request_started
        request_started.disconnect(self._reset_stuck_runs)
        try:
            from datetime import timedelta
            from django.utils import timezone
            from apps.comparison.models import ComparisonRun
            cutoff = timezone.now() - timedelta(seconds=90)
            ComparisonRun.objects.filter(
                status=ComparisonRun.RUNNING,
                created_at__lt=cutoff,
            ).update(
                status=ComparisonRun.FAILED,
                error_message='Server restarted — run did not complete. Please try again.',
            )
        except Exception:
            pass
