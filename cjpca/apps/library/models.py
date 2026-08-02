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

    # language — decides which ingestion + retrieval pipeline a document uses.
    # 'en' = the main pipeline (docling + bge-small-en, English collection);
    # 'ar' = the Arabic pipeline (kraken/text extract + bge-m3, regulations_ar).
    ENGLISH = 'en'
    ARABIC  = 'ar'
    LANGUAGE_CHOICES = [(ENGLISH, 'English'), (ARABIC, 'Arabic')]

    # chunking strategy — how the document was split into legal nodes. Chosen in
    # the guided-upload wizard (Screen 6). 'auto' == article-based, the detected
    # default; 'section' merges each section's articles into one node; 'clause'
    # splits each article on its numbered/lettered clause markers.
    CHUNK_AUTO    = 'auto'
    CHUNK_ARTICLE = 'article'
    CHUNK_SECTION = 'section'
    CHUNK_CLAUSE  = 'clause'
    CHUNK_STRATEGY_CHOICES = [
        (CHUNK_AUTO, 'Automatic'), (CHUNK_ARTICLE, 'Article-based'),
        (CHUNK_SECTION, 'Section-based'), (CHUNK_CLAUSE, 'Clause-based'),
    ]

    # citation format — how a source is labelled when cited (Screen 7).
    # 'short' → "PDPL, Article 12"; 'full' → "Law No. 30 of 2018, Article 12";
    # 'custom' → user template with {doc}/{num}/{year}/{article} placeholders.
    CITE_SHORT  = 'short'
    CITE_FULL   = 'full'
    CITE_CUSTOM = 'custom'
    CITATION_FORMAT_CHOICES = [
        (CITE_SHORT, 'Document + Article'), (CITE_FULL, 'Full legal citation'),
        (CITE_CUSTOM, 'Custom'),
    ]

    # confidentiality (Screen 4)
    CONF_PUBLIC       = 'public'
    CONF_INTERNAL     = 'internal'
    CONF_CONFIDENTIAL = 'confidential'
    CONFIDENTIALITY_CHOICES = [
        (CONF_PUBLIC, 'Public'), (CONF_INTERNAL, 'Internal'),
        (CONF_CONFIDENTIAL, 'Confidential'),
    ]

    # classification lifecycle (results-first coverage). Classifying a policy's
    # sections into taxonomy topics is opt-in at upload; the coverage page reads
    # this to show a "not classified / classifying / ready" state instead of
    # silently running the model inside a page request.
    CLASS_NONE    = 'none'      # never classified
    CLASS_PENDING = 'pending'   # queued, worker not started
    CLASS_RUNNING = 'running'   # classifier in progress
    CLASS_DONE    = 'done'      # tags written at classification_version
    CLASSIFICATION_CHOICES = [
        (CLASS_NONE, 'Not classified'), (CLASS_PENDING, 'Queued'),
        (CLASS_RUNNING, 'Classifying'), (CLASS_DONE, 'Ready'),
    ]

    name              = models.CharField(max_length=255)
    full_name         = models.CharField(max_length=500, blank=True)
    doc_type          = models.CharField(max_length=20, choices=DOC_TYPE_CHOICES)
    jurisdiction      = models.CharField(max_length=20, choices=JURISDICTION_CHOICES, blank=True)
    language          = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default=ENGLISH)
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

    # ── Guided-upload wizard: confirmed config (Screens 4, 6, 7) ──
    chunk_strategy    = models.CharField(max_length=10, choices=CHUNK_STRATEGY_CHOICES, default=CHUNK_AUTO)
    citation_format   = models.CharField(max_length=10, choices=CITATION_FORMAT_CHOICES, default=CITE_SHORT)
    citation_template = models.CharField(max_length=200, blank=True)   # used when citation_format == custom
    citation_abbr     = models.CharField(max_length=40,  blank=True)   # short label, e.g. "PDPL"
    doc_year          = models.CharField(max_length=8,   blank=True)   # "2018"
    department        = models.CharField(max_length=40,  blank=True)   # Legal / Compliance / Risk / …
    confidentiality   = models.CharField(max_length=20, choices=CONFIDENTIALITY_CHOICES, blank=True)

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

    # ── Coverage / caching ──
    # sha256 of the source file bytes. Cache key for mapping results and the
    # invalidation trigger for classification: if a doc is re-uploaded with
    # changed content the hash changes and stale tags/results are ignored.
    content_hash         = models.CharField(max_length=64, blank=True, db_index=True)
    classification_state = models.CharField(max_length=12, choices=CLASSIFICATION_CHOICES,
                                            default=CLASS_NONE)
    classified_at        = models.DateTimeField(null=True, blank=True)
    # taxonomy fingerprint the chunk tags were written under (staleness check).
    classification_version = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ['-upload_date']

    def __str__(self):
        return self.name

    def compute_content_hash(self) -> str:
        """sha256 of the stored file's bytes. Empty string if no file.
        Streamed so large PDFs don't load fully into memory."""
        import hashlib
        if not self.file or not self.file.name:
            return ''
        h = hashlib.sha256()
        try:
            self.file.open('rb')
            for block in iter(lambda: self.file.read(65536), b''):
                h.update(block)
        except (FileNotFoundError, ValueError):
            return ''
        finally:
            try:
                self.file.close()
            except Exception:
                pass
        return h.hexdigest()

    def cited_as(self, article: str = '') -> str:
        """Format a citation for this document using the configured format.

        ``article`` is a label like "Article 12" (already localised by the
        caller). Powers the Screen 7 live preview and the Copilot source labels.
        """
        abbr = (self.citation_abbr or self.name or '').strip()
        art = (article or '').strip()
        if self.citation_format == self.CITE_FULL:
            num = (self.document_id or '').strip()
            head = f"Law No. {num}" if num else (self.full_name or self.name)
            if self.doc_year:
                head = f"{head} of {self.doc_year}"
            return f"{head}, {art}" if art else head
        if self.citation_format == self.CITE_CUSTOM and self.citation_template:
            return (self.citation_template
                    .replace('{doc}', abbr)
                    .replace('{num}', (self.document_id or '').strip())
                    .replace('{year}', self.doc_year or '')
                    .replace('{article}', art)).strip()
        # short (default): "PDPL, Article 12"
        return f"{abbr}, {art}" if art else abbr

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


class TaxonomyNode(models.Model):
    """Admin-managed compliance hierarchy — jurisdictions → regions → countries →
    sections, internal policy trees, topic taxonomies, etc.

    A single self-referential tree so admins can model any structure they need
    instead of relying on the hardcoded jurisdiction list. Deliberately generic:
    ``node_type`` labels the role of a node, ``parent`` builds the hierarchy.
    Nothing else in the app reads from this yet — it's a standalone manager.
    """
    ROOT     = 'root'
    REGION   = 'region'
    COUNTRY  = 'country'
    SECTION  = 'section'
    TOPIC    = 'topic'
    GROUP    = 'group'
    OTHER    = 'other'
    TYPE_CHOICES = [
        (ROOT, 'Category'), (REGION, 'Region'), (COUNTRY, 'Country'),
        (SECTION, 'Section'), (TOPIC, 'Topic'), (GROUP, 'Group'), (OTHER, 'Other'),
    ]
    # A small colour/emoji hint per type for the tree UI
    TYPE_META = {
        ROOT:    ('#002583', 'Category'),
        REGION:  ('#2563EB', 'Region'),
        COUNTRY: ('#16A34A', 'Country'),
        SECTION: ('#D97706', 'Section'),
        TOPIC:   ('#7C3AED', 'Topic'),
        GROUP:   ('#0891B2', 'Group'),
        OTHER:   ('#64748B', 'Item'),
    }

    name        = models.CharField(max_length=120)
    node_type   = models.CharField(max_length=12, choices=TYPE_CHOICES, default=OTHER)
    code        = models.CharField(max_length=40, blank=True)   # e.g. "bahrain", "BH"
    description = models.CharField(max_length=300, blank=True)
    parent      = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE,
                                    related_name='children')
    order       = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def type_color(self):
        return self.TYPE_META.get(self.node_type, self.TYPE_META[self.OTHER])[0]

    @property
    def type_label(self):
        return self.TYPE_META.get(self.node_type, self.TYPE_META[self.OTHER])[1]

    def descendant_count(self):
        n = 0
        for c in self.children.all():
            n += 1 + c.descendant_count()
        return n
