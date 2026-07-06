from django.apps import AppConfig


class LibraryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.library'
    label = 'library'

    def ready(self):
        from . import signals  # noqa: F401 — registers pre_delete chunk purge
