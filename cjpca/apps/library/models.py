from django.db import models


class Document(models.Model):
    # doc_type
    REGULATION = 'regulation'
    POLICY = 'policy'
    DOC_TYPE_CHOICES = [(REGULATION, 'Regulation'), (POLICY, 'Policy')]

    # status
    INDEXED = 'indexed'
    PROCESSING = 'processing'
    FAILED = 'failed'
    STATUS_CHOICES = [
        (INDEXED, 'Indexed'),
        (PROCESSING, 'Processing'),
        (FAILED, 'Failed'),
    ]

    # jurisdiction
    EU      = 'eu'
    BAHRAIN = 'bahrain'
    INDIA   = 'india'
    KUWAIT  = 'kuwait'
    BBK     = 'bbk'
    SAUDI   = 'saudi'
    UAE     = 'uae'
    OTHER   = 'other'
    JURISDICTION_CHOICES = [
        (BAHRAIN, 'Bahrain'),
        (INDIA,   'India'),
        (KUWAIT,  'Kuwait'),
        (BBK,     'BBK'),
        (OTHER,   'Other'),
    ]

    name              = models.CharField(max_length=255)
    full_name         = models.CharField(max_length=500, blank=True)
    doc_type          = models.CharField(max_length=20, choices=DOC_TYPE_CHOICES)
    jurisdiction      = models.CharField(max_length=20, choices=JURISDICTION_CHOICES, blank=True)
    version           = models.CharField(max_length=50, blank=True)
    issuing_authority = models.CharField(max_length=255, blank=True)
    effective_date    = models.DateField(null=True, blank=True)
    source_url        = models.URLField(max_length=500, blank=True)
    notes             = models.TextField(blank=True)
    status            = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PROCESSING)
    upload_date       = models.DateTimeField(auto_now_add=True)
    chunk_count       = models.PositiveIntegerField(default=0)
    token_count       = models.PositiveIntegerField(default=0)
    file              = models.FileField(upload_to='documents/', blank=True)
    tags              = models.JSONField(default=list, blank=True)
    cached_topics     = models.JSONField(default=list, blank=True)

    # ── Hydrated from data/metadata.csv via `manage.py full_ingest` ──
    # These fields make the side-panel detail richer. Effective_date already
    # existed; the rest are new. All optional so legacy / user-uploaded docs
    # still work fine without them.
    publication_date    = models.DateField(null=True, blank=True)
    last_updated        = models.DateField(null=True, blank=True)
    section_identifiers = models.CharField(max_length=255, blank=True)   # "Articles 1-6"
    document_id         = models.CharField(max_length=50,  blank=True, db_index=True)  # "BH-PDPA-O43"
    regulation_category = models.CharField(max_length=50,  blank=True)
    privacy_relevance   = models.CharField(max_length=20,  blank=True)   # high|partial|...
    applicable_sector   = models.CharField(max_length=50,  blank=True)
    superseded          = models.BooleanField(default=False)
    superseded_by       = models.CharField(max_length=255, blank=True)   # stem of newer doc
    parent_regulation   = models.CharField(max_length=50,  blank=True)
    cross_references    = models.TextField(blank=True)
    concept_tags_csv    = models.JSONField(default=list, blank=True)     # from the CSV column

    class Meta:
        ordering = ['-upload_date']

    def __str__(self):
        return self.name

    @property
    def chunk_doc_title(self) -> str:
        """The value the ingestion pipeline writes into chunk metadata as
        ``doc_title``. Used by the reasoning workflows when they constrain
        retrieval to this specific document.

        Source of truth: ``Path(self.file.name).stem`` — matches what
        ingestion/loaders.py uses when chunking. The display ``name`` field
        does NOT match (e.g., name="PDPA Ministerial Order 43/2022", actual
        chunk title="Bahrain_PDPA_Order_43_2022_Technical_Organisational_Measures").
        Filtering on ``name`` produces zero hits and silently empty workflows
        — bug surfaced as "comparison ran, 0 obligations" in the live UI.
        """
        if not self.file or not self.file.name:
            return ''
        from pathlib import Path
        return Path(self.file.name).stem
