"""Site-wide configuration an administrator can change from the UI.

Kept in `core` rather than a feature app because these are cross-cutting
presentation choices — every page reads them, no single feature owns them.
"""

from django.conf import settings
from django.core.cache import cache
from django.db import models


class SiteSetting(models.Model):
    """Singleton row (always pk=1) holding management configuration.

    Never query this directly — use ``SiteSetting.load()``, which creates the
    row on first access so a fresh install has working defaults without a
    data migration.
    """

    # ── Jurisdiction display ────────────────────────────────────────────────
    # How a document's jurisdiction is rendered in tables, pickers and scope
    # headers. Default is NAME: flag imagery is decorative, and the country
    # word is what an auditor reads. Admins who prefer the flags can switch.
    NAME = 'name'
    FLAG = 'flag'
    BOTH = 'both'
    JURISDICTION_DISPLAY_CHOICES = [
        (NAME, 'Country name only'),
        (FLAG, 'Flag only'),
        (BOTH, 'Flag and country name'),
    ]

    jurisdiction_display = models.CharField(
        max_length=8,
        choices=JURISDICTION_DISPLAY_CHOICES,
        default=NAME,
        help_text='How a document’s jurisdiction is shown across the site.',
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )

    # Cached separately from the instance: the context processor runs on every
    # request and only ever needs the mode string, so there is no reason to
    # pickle a model (and a FK) into the cache for it.
    _MODE_CACHE_KEY = 'site_setting_jurisdiction_display'
    _MODE_CACHE_TTL = 300  # seconds

    class Meta:
        verbose_name = 'site setting'
        verbose_name_plural = 'site settings'

    def __str__(self):
        return f'Site settings (jurisdiction: {self.jurisdiction_display})'

    def save(self, *args, **kwargs):
        # Force the singleton pk so a stray SiteSetting() can never create a
        # second row that silently shadows the real one.
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self._MODE_CACHE_KEY)

    def delete(self, *args, **kwargs):  # pragma: no cover - defensive
        """Refuse deletion: every page reads this row."""
        return

    @classmethod
    def load(cls):
        """The settings row, created with defaults if it doesn't exist yet."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def jurisdiction_mode(cls):
        """Just the display mode, cached — the hot path for every request.

        Falls back to NAME if the table isn't migrated yet, so an un-migrated
        checkout renders instead of 500ing on every page.
        """
        mode = cache.get(cls._MODE_CACHE_KEY)
        if mode is None:
            try:
                mode = cls.load().jurisdiction_display
            except Exception:
                mode = cls.NAME
            cache.set(cls._MODE_CACHE_KEY, mode, cls._MODE_CACHE_TTL)
        return mode
