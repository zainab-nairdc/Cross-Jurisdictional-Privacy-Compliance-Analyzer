import threading

from django.apps import AppConfig


class IngestionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ingestion'
    label = 'ingestion'

    def ready(self):
        # Pre-warm the embedding model in a background thread so the first
        # search/ingestion request doesn't block for 10+ seconds loading ~500 MB.
        t = threading.Thread(target=self._warmup_models, daemon=True)
        t.start()

    @staticmethod
    def _warmup_models():
        try:
            from ingestion.embedder import get_model
            get_model()
        except Exception:
            pass
