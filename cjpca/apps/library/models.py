from django.conf import settings
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
    # Human-readable reason a document ended up in FAILED ("needs attention"),
    # captured at the point of failure so the UI can tell the user what went
    # wrong and what to do — instead of a bare red dot.
    status_detail     = models.CharField(max_length=500, blank=True, default='')
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
    # Explicit version lineage set by the uploader ("this is a newer version of
    # <existing regulation>"). Defines the version FAMILY deliberately — a human
    # says two documents are the same law — instead of guessing from names.
    version_of          = models.ForeignKey('self', null=True, blank=True,
                                            on_delete=models.SET_NULL,
                                            related_name='newer_versions')
    cross_references    = models.TextField(blank=True)
    concept_tags_csv    = models.JSONField(default=list, blank=True)     # key topics (LLM-extracted)
    scope_summary       = models.TextField(blank=True, default='')       # one-line "what/who it governs"

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

    @property
    def attention(self):
        """For a FAILED ('needs attention') document, a plain-language summary of
        what went wrong plus concrete next steps — classified from the captured
        `status_detail`. Returns None when the document is fine."""
        if self.status != self.FAILED:
            return None
        detail = (self.status_detail or '').strip()
        low = detail.lower()
        if any(k in low for k in ('ollama', 'connection', 'refused', 'timed out', 'timeout', 'engine')):
            summary = "The local AI engine (Ollama) wasn’t reachable while indexing this document."
            actions = ["Start Ollama — open the app, or run `ollama serve` in a terminal.",
                       "Then delete this document and upload it again."]
        elif any(k in low for k in ('ocr', 'scanned', 'image', 'text layer', 'no text', 'empty')):
            summary = "The document’s text couldn’t be read — it looks like a scanned or image-only file."
            actions = ["Open the file and check the text is selectable, not a picture.",
                       "Re-save it as a text-based PDF (or run OCR on it), then upload again."]
        elif any(k in low for k in ('unsupported', 'format', '.doc', 'parse', 'corrupt', 'fzerror', 'password', 'encrypted')):
            summary = "The file couldn’t be opened — it may be an unsupported, encrypted or corrupt format."
            actions = ["Make sure it’s a real PDF, .docx or .txt (legacy .doc and password-protected files aren’t supported).",
                       "Export a clean, unprotected copy and upload it again."]
        else:
            summary = "This document failed while being indexed."
            actions = ["Check the file opens and is a valid PDF, .docx or .txt.",
                       "Make sure the local AI engine (Ollama) is running.",
                       "Delete this document and upload it again."]
        return {"detail": detail, "summary": summary, "actions": actions}

    # ── Version management ─────────────────────────────────────────────────────
    @property
    def version_status(self) -> str:
        """'superseded' | 'upcoming' | 'in_force', derived from the supersede flag
        and the effective date. Exactly one version of a regulation should be
        'in_force' at a time."""
        if self.superseded:
            return 'superseded'
        from django.utils import timezone
        if self.effective_date and self.effective_date > timezone.now().date():
            return 'upcoming'
        return 'in_force'

    @property
    def family_root_id(self):
        """The pk of the oldest ancestor in this document's version lineage —
        the stable identity of the LAW across all its versions. A document with
        no `version_of` is its own root. Walks the explicit `version_of` chain
        (guarded against cycles). Two documents in the same family share a root."""
        d, seen = self, set()
        while d.version_of_id and d.version_of_id not in seen:
            seen.add(d.pk)
            d = d.version_of
        return d.pk

    def version_family(self):
        """Every OTHER document that is a version of the same law — i.e. shares
        this document's family root, established by the explicit `version_of`
        link the uploader set. Falls back to the legacy document_id/supersede
        match for documents linked before explicit lineage existed."""
        root = self.family_root_id
        # Everything whose lineage rolls up to the same root.
        ids = [d.pk for d in Document.objects.all().only('id', 'version_of')
               if d.family_root_id == root]
        from django.db.models import Q
        keys = Q(pk__in=ids)
        # Legacy fallback (pre-lineage links).
        if self.document_id:
            keys |= Q(document_id=self.document_id)
        stem = self.chunk_doc_title
        if stem:
            keys |= Q(parent_regulation=stem) | Q(superseded_by=stem)
        if self.parent_regulation:
            keys |= Q(document_id=self.parent_regulation)
        return Document.objects.filter(keys).exclude(pk=self.pk)

    def affected_approved_analyses(self):
        """Approved comparison results whose run used THIS document — the work that
        would need re-review if this version is superseded. Returns a queryset (may
        be empty), or None if the comparison app isn't available."""
        try:
            from django.db.models import Q
            from apps.comparison.models import ComparisonResult
            return ComparisonResult.objects.filter(
                Q(run__reg_a=self) | Q(run__reg_b=self),
                lifecycle=ComparisonResult.APPROVED)
        except Exception:
            return None

    def supersede_with(self, new_version, actor=None):
        """Mark THIS version superseded by `new_version`, link the lineage, and
        return the approved analyses affected (for the 're-review recommended'
        flag). Never deletes the old version — history is preserved for audit."""
        self.superseded = True
        self.superseded_by = new_version.chunk_doc_title or new_version.name
        self.save(update_fields=['superseded', 'superseded_by'])

        new_version.parent_regulation = self.document_id or self.chunk_doc_title
        if self.document_id and not new_version.document_id:
            new_version.document_id = self.document_id
        # Establish the explicit lineage if it wasn't set at upload, so the two
        # versions are a proper family going forward (unless it would form a cycle).
        if not new_version.version_of_id and new_version.pk != self.pk:
            new_version.version_of = self
        new_version.superseded = False
        new_version.save(update_fields=['parent_regulation', 'document_id',
                                        'superseded', 'version_of'])

        affected = self.affected_approved_analyses()

        # Push-invalidate the comparison assessments built on this document.
        # Without it a superseded source would keep showing as current until
        # somebody happened to open the Approved Runs page.
        #
        # Delegated entirely to the comparison app's currency assessment — this
        # decides WHEN to re-check, never WHAT current means. Best-effort and
        # last in the method, so a comparison-side problem can never leave the
        # supersession itself half-applied.
        invalidated = {}
        try:
            from apps.comparison.assessments import invalidate_runs_for_document
            invalidated = invalidate_runs_for_document(self)
        except Exception:
            pass

        try:
            from apps.history.audit import log_event, Actions
            log_event(actor, Actions.DOC_SUPERSEDED,
                      target_type='library.Document', target_id=self.pk,
                      description=f'{self.name} superseded by {new_version.name}',
                      metadata={'superseded_by': new_version.chunk_doc_title,
                                'affected_approved': affected.count() if affected is not None else 0,
                                'runs_rechecked': sum(
                                    v for k, v in invalidated.items()
                                    if k not in ('errors', 'changed')),
                                'runs_state_changed': invalidated.get('changed', 0)})
        except Exception:
            pass
        return affected


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


# ── Requirement — canonical, regulation-level knowledge ──────────────────────

class Requirement(models.Model):
    """One regulatory requirement, owned by a REGULATION rather than by a run.

    The distinction this model exists to make:

      a Requirement is persistent canonical knowledge — what a regulation
      demands, extracted once and reused;
      an ObligationMapping is a run-specific observation — whether one policy
      satisfied that demand on one occasion.

    Before this, obligations existed only as rows hanging off a MappingAnalysis,
    so analysing the same regulation twice produced two unrelated obligation
    sets with no way to say they were about the same thing. Requirements are
    keyed per regulation VERSION: a new version is a separate Document and gets
    its own extraction, because asserting that v2's obligations equal v1's is a
    judgement no code should make silently (see `carried_from`).
    """

    MIGRATED = 'migrated'
    LLM      = 'llm'
    HUMAN    = 'human'
    SOURCE_CHOICES = [
        (MIGRATED, 'Migrated from legacy analysis rows'),
        (LLM,      'Extracted by the local model'),
        (HUMAN,    'Written or corrected by a person'),
    ]

    CRITICAL = 'critical'
    HIGH     = 'high'
    MEDIUM   = 'medium'
    LOW      = 'low'
    SEVERITY_CHOICES = [
        (CRITICAL, 'Critical'), (HIGH, 'High'),
        (MEDIUM,   'Medium'),   (LOW,  'Low'),
    ]

    regulation      = models.ForeignKey('library.Document', on_delete=models.CASCADE,
                                        related_name='requirements')
    # Identity. Deterministic (see apps.library.requirements.make_key) so the
    # same source yields the same key on every run — that is what makes both the
    # backfill and ensure_requirements idempotent.
    key             = models.CharField(max_length=40, db_index=True)

    text            = models.TextField()
    title           = models.CharField(max_length=300, blank=True)

    # ── Provenance, NOT identity ──
    # A chunk is not permanently equivalent to one requirement: a single
    # provision can impose several obligations, and a later extraction must be
    # free to record them separately. So this is indexed but deliberately NOT
    # unique — uniqueness lives on (regulation, key).
    article_ref     = models.CharField(max_length=100, blank=True)
    source_chunk_id = models.CharField(max_length=64, blank=True, db_index=True)
    source_quote    = models.TextField(blank=True)

    # DERIVED COMPATIBILITY MIRROR — NOT AUTHORITATIVE.
    #
    # The authoritative topic representation is the RequirementTopic rows on
    # `topic_assignments`, which resolve against reasoning/taxonomy.py. This
    # field holds a flat list of the OFFICIAL matched topic tags from those
    # rows, in rank order, e.g. ["retention", "security"], and is refreshed by
    # apps.library.topics.sync_topics_mirror().
    #
    # It previously held whatever free-text tags the extractor's model happened
    # to emit ("1-3 short lowercase subject tags"), validated against nothing.
    # Nothing read it, which is the only reason that was harmless. It is kept
    # populated so any future reader gets controlled values instead, but new
    # code must read `topic_assignments`: this field cannot express a
    # subcategory, a confidence, an unresolved concept, or which taxonomy
    # version produced it.
    topics            = models.JSONField(default=list, blank=True)
    # The seriousness of the OBLIGATION itself. Distinct from
    # ObligationMapping.severity, which grades a run's coverage verdict and is
    # left exactly as it was.
    inherent_severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES,
                                         null=True, blank=True)
    applicability     = models.CharField(max_length=200, blank=True)
    scope_note        = models.TextField(blank=True)

    # Version lineage. Set only when someone establishes that this requirement
    # continues one from an earlier version — never inferred.
    carried_from      = models.ForeignKey('self', null=True, blank=True,
                                          on_delete=models.SET_NULL,
                                          related_name='carried_to')

    extraction_source = models.CharField(max_length=12, choices=SOURCE_CHOICES,
                                         default=LLM, db_index=True)
    extraction_model  = models.CharField(max_length=64, blank=True)

    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['regulation_id', 'article_ref', 'id']
        constraints = [
            models.UniqueConstraint(fields=['regulation', 'key'],
                                    name='uniq_requirement_key_per_regulation'),
        ]

    def __str__(self):
        return f'{self.article_ref or "?"} — {(self.title or self.text)[:60]}'

    @property
    def is_migrated(self) -> bool:
        """Migrated rows are a grounded baseline rebuilt from what past runs
        cited, not output of the extraction pipeline. Kept distinguishable so
        they are never mistaken for a native extraction."""
        return self.extraction_source == self.MIGRATED


# ── RequirementReference — legal cross-references, made explicit ─────────────

class RequirementReference(models.Model):
    """One legal cross-reference carried by a Requirement's source provision.

    "The Authority shall perform the duties referred to in Article 31" is not a
    self-contained rule — it points somewhere, and a requirement that loses the
    pointer reads as complete when it is not. This model keeps the pointer as a
    pointer: the referenced text is NEVER copied into Requirement.text, because
    doing so would manufacture a provision that no legislator enacted.

    The traceability chain this completes:

        Requirement -> source provision (source_chunk_id)
                    -> referenced provision(s) (target_chunk_id / candidates)

    DETECTION AND RESOLUTION ARE SEPARATE, and `status` is what keeps them
    apart. A reference that was found but could not be safely pointed at a
    chunk is preserved as detected-and-unresolved rather than discarded — a
    reference we cannot follow is still a fact about the provision.

    The governing rule is that a WRONG link is far worse than a missing one: it
    manufactures traceability a reviewer has no way to audit. So every path
    here prefers `ambiguous` or `unresolved` over a guess, and `candidates`
    exists precisely so a 1-to-many outcome can be recorded honestly instead of
    being collapsed to whichever chunk happened to sort first.
    """

    # ── ref_kind ──
    ARTICLE   = 'article'
    SECTION   = 'section'
    CLAUSE    = 'clause'
    PARAGRAPH = 'paragraph'
    SCHEDULE  = 'schedule'
    LAW       = 'law'
    UNKNOWN   = 'unknown'
    KIND_CHOICES = [
        (ARTICLE, 'Article'), (SECTION, 'Section'), (CLAUSE, 'Clause'),
        (PARAGRAPH, 'Paragraph'), (SCHEDULE, 'Schedule'),
        (LAW, 'Law / instrument'), (UNKNOWN, 'Unknown'),
    ]

    # ── scope ──
    # INTERNAL — points inside the regulation that owns the requirement
    # EXTERNAL — names another instrument
    # UNKNOWN  — a bare "Article 31" with nothing saying which instrument.
    #            Probably internal, but probably is not a fact; resolution
    #            upgrades it to INTERNAL only if it actually resolves here.
    INTERNAL = 'internal'
    EXTERNAL = 'external'
    SCOPE_UNKNOWN = 'unknown'
    SCOPE_CHOICES = [
        (INTERNAL, 'Internal (same document)'),
        (EXTERNAL, 'External (another document)'),
        (SCOPE_UNKNOWN, 'Unknown'),
    ]

    # ── status ──
    # DETECTED   — found, resolution not yet attempted
    # RESOLVED   — points at EXACTLY ONE chunk, recorded in target_chunk_id
    # AMBIGUOUS  — the reference does not designate exactly one chunk, and
    #              every valid target is listed in `candidates`. Covers both
    #              real cases: one article split across several chunks by
    #              clause-chunking, and a range that names many provisions.
    # UNRESOLVED — no safe target could be established. Includes the case
    #              where the target DOCUMENT is known but the provision inside
    #              it is not: document-level identification is explicitly NOT
    #              provision-level resolution.
    DETECTED   = 'detected'
    RESOLVED   = 'resolved'
    AMBIGUOUS  = 'ambiguous'
    UNRESOLVED = 'unresolved'
    STATUS_CHOICES = [
        (DETECTED, 'Detected'), (RESOLVED, 'Resolved'),
        (AMBIGUOUS, 'Ambiguous'), (UNRESOLVED, 'Unresolved'),
    ]

    # ── detected_by ──
    REGEX = 'regex'
    LLM   = 'llm'
    DETECTED_BY_CHOICES = [(REGEX, 'Deterministic detector'), (LLM, 'Model')]

    requirement     = models.ForeignKey('library.Requirement', on_delete=models.CASCADE,
                                        related_name='references')

    # The matched source wording, verbatim. Never normalised, never rewritten —
    # this is the audit record of what the provision actually said, and it must
    # survive every re-run of detection unchanged.
    ref_text        = models.CharField(max_length=300)

    ref_kind        = models.CharField(max_length=12, choices=KIND_CHOICES,
                                       default=UNKNOWN, db_index=True)
    # Normalised designation. Closed grammar: "31", "31(2)", "31-35",
    # "preceding" / "following" / "self", "self(1)", or "". Fixed at detection
    # and never rewritten by resolution — that is what lets it sit in the
    # uniqueness key without a re-run creating duplicates.
    ref_number      = models.CharField(max_length=40, blank=True, db_index=True)

    scope           = models.CharField(max_length=10, choices=SCOPE_CHOICES,
                                       default=SCOPE_UNKNOWN, db_index=True)
    status          = models.CharField(max_length=12, choices=STATUS_CHOICES,
                                       default=DETECTED, db_index=True)

    # Set ONLY when exactly one chunk is the target. Empty on every other
    # status, so a populated value always means a single safe link.
    target_chunk_id = models.CharField(max_length=64, blank=True, db_index=True)
    # The document the reference lands in. May be set while status is still
    # UNRESOLVED — knowing WHICH law is cited is genuinely useful and is a
    # weaker claim than knowing which provision.
    target_document = models.ForeignKey('library.Document', null=True, blank=True,
                                        on_delete=models.SET_NULL,
                                        related_name='referenced_by')
    target_doc_code = models.CharField(max_length=50, blank=True)

    # Every valid target when there is not exactly one. Node ids, in stored
    # order. Populated on AMBIGUOUS, and on a partially-resolvable range where
    # some targets were found and others were missing.
    candidates      = models.JSONField(default=list, blank=True)

    confidence      = models.FloatField(default=0.0)
    detected_by     = models.CharField(max_length=8, choices=DETECTED_BY_CHOICES,
                                       default=REGEX, db_index=True)

    # Why resolution ended where it did. Human-readable, for the reviewer and
    # for diagnosing the detector without re-running it.
    resolution_note = models.CharField(max_length=300, blank=True)

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['requirement_id', 'id']
        constraints = [
            # Idempotency for the detector. Keyed on the three fields fixed at
            # DETECTION time, never on anything resolution computes, so a
            # re-run updates the resolution of an existing row instead of
            # filing a second copy of the same reference.
            models.UniqueConstraint(
                fields=['requirement', 'ref_kind', 'ref_number', 'ref_text'],
                name='uniq_reference_per_requirement'),
        ]
        indexes = [
            models.Index(fields=['status', 'scope']),
        ]

    def __str__(self):
        return f'{self.ref_text} -> {self.status}'

    @property
    def is_resolved(self) -> bool:
        return self.status == self.RESOLVED

    @property
    def needs_human(self) -> bool:
        """Ambiguous references are the ones a person can actually settle."""
        return self.status == self.AMBIGUOUS


# ── RequirementTopic — the canonical multi-topic assignment ──────────────────

class RequirementTopic(models.Model):
    """One topic assignment for one requirement. A requirement may have many.

    This is the AUTHORITATIVE topic representation:

        Requirement -> RequirementTopic -> reasoning/taxonomy.py

    `Requirement.topics` is a derived compatibility mirror and is not the
    source of truth. See `Requirement.topics` and
    `apps.library.topics.sync_topics_mirror`.

    Why multi-row rather than a wider Requirement: a single legal requirement
    routinely concerns several topics at once. "Retain personal data no longer
    than necessary and protect it with appropriate technical measures" is
    genuinely retention AND security, and forcing a choice loses half of what
    the provision says. Nothing in this schema assumes one topic per
    requirement, and nothing caps how many there may be — the cap in
    `reasoning.requirement_classify.MAX_TOPICS` bounds MODEL OUTPUT only.

    Rows are also how an UNRESOLVED concept survives. A concept the model
    considered meaningful but which no official topic represents is stored with
    `assignment=SUGGESTED` and a blank `topic`, preserving the model's original
    wording, its evidence and the taxonomy version it was produced under. That
    is the input to the human-reviewed suggestion workflow — it is deliberately
    NOT an official topic, and storing it here creates no taxonomy entry.
    """

    # ── assignment ──
    # MATCHED      — resolved onto an official topic by resolve_concept()
    # SUGGESTED    — a meaningful concept the taxonomy does not represent.
    #                `topic` is blank. Awaits human review.
    # UNCLASSIFIED — nothing to classify, or the model was below the
    #                confidence floor. `topic` is blank. NOT a taxonomy gap.
    # HUMAN        — a person assigned this. Survives reclassification.
    MATCHED      = 'matched'
    SUGGESTED    = 'suggested'
    UNCLASSIFIED = 'unclassified'
    HUMAN        = 'human'
    ASSIGNMENT_CHOICES = [
        (MATCHED, 'Matched to an official topic'),
        (SUGGESTED, 'Suggested — no official topic fits'),
        (UNCLASSIFIED, 'Unclassified'),
        (HUMAN, 'Assigned by a person'),
    ]
    # Assignments that carry an official topic and belong in the mirror.
    OFFICIAL_ASSIGNMENTS = (MATCHED, HUMAN)

    # ── resolution_method ── mirrors reasoning.taxonomy's METHOD_* constants.
    EXACT      = 'exact'
    ALIAS      = 'alias'
    NORMALIZED = 'normalized'
    SEMANTIC   = 'semantic'
    HUMAN_M    = 'human'
    NONE       = 'none'
    METHOD_CHOICES = [
        (EXACT, 'Exact tag'), (ALIAS, 'Curated alias'),
        (NORMALIZED, 'Normalised name'), (SEMANTIC, 'Semantic similarity'),
        (HUMAN_M, 'Human decision'), (NONE, 'Not resolved'),
    ]

    requirement       = models.ForeignKey('library.Requirement',
                                          on_delete=models.CASCADE,
                                          related_name='topic_assignments')

    # Official taxonomy tag. BLANK for SUGGESTED and UNCLASSIFIED rows — a row
    # without an official topic is a real and expected state, not a defect.
    topic             = models.CharField(max_length=64, blank=True, db_index=True)
    subcategory       = models.CharField(max_length=64, blank=True)

    # The model's own confidence, stored verbatim for audit. Never treated as
    # truth, and never invented when the model did not state one.
    confidence        = models.FloatField(default=0.0)

    assignment        = models.CharField(max_length=12, choices=ASSIGNMENT_CHOICES,
                                         default=MATCHED, db_index=True)
    # Ordering of this requirement's assignments, 0 first. rank=0 does NOT mean
    # "the only correct topic" — a requirement can have several equally
    # legitimate topics, and lower-ranked ones are not lesser findings.
    rank              = models.PositiveSmallIntegerField(default=0)

    # The model's ORIGINAL wording, always preserved even when it resolved to
    # something else ("data storage period" -> retention via alias). This is
    # what makes an assignment auditable and what lets Phase 3 recognise two
    # requirements as having raised the same underlying concept.
    model_concept     = models.CharField(max_length=200, blank=True)
    resolution_method = models.CharField(max_length=12, choices=METHOD_CHOICES,
                                         default=NONE)

    # The review item this open concept was folded into, when one exists.
    # Set only on SUGGESTED rows. SET_NULL because deleting a suggestion must
    # not delete the requirement's record that the concept was raised.
    suggestion        = models.ForeignKey('library.TopicSuggestion', null=True,
                                          blank=True, on_delete=models.SET_NULL,
                                          related_name='assignments')

    # Short phrase from the requirement or its source provision supporting the
    # assignment. An assignment nothing can be pointed at is one that should
    # not have been made.
    evidence          = models.CharField(max_length=500, blank=True)
    # Only meaningful on SUGGESTED rows: what the model says the concept is and
    # why it considers the official topics inadequate. Phase 3 reads these.
    reason            = models.CharField(max_length=500, blank=True)
    why_insufficient  = models.CharField(max_length=500, blank=True)

    # Which vocabulary and which model produced this. Without them a stale
    # assignment is indistinguishable from a current one.
    taxonomy_version  = models.CharField(max_length=32, blank=True, db_index=True)
    model_version     = models.CharField(max_length=64, blank=True)

    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['requirement_id', 'rank', 'id']
        constraints = [
            # One row per official leaf per requirement. Partial, because
            # SUGGESTED and UNCLASSIFIED rows all share topic='' and would
            # otherwise collide with each other — which would cap a
            # requirement at a single unresolved concept.
            models.UniqueConstraint(
                fields=['requirement', 'topic', 'subcategory'],
                condition=~models.Q(topic=''),
                name='uniq_official_topic_per_requirement'),
            # The complement: open concepts are keyed by the model's wording,
            # so two different unresolved concepts coexist but the same one
            # twice does not.
            models.UniqueConstraint(
                fields=['requirement', 'model_concept'],
                condition=models.Q(topic=''),
                name='uniq_open_concept_per_requirement'),
        ]
        indexes = [
            models.Index(fields=['assignment', 'topic']),
            models.Index(fields=['taxonomy_version', 'assignment']),
        ]

    def __str__(self):
        return f'{self.topic or self.model_concept or "?"} ({self.assignment})'

    @property
    def is_official(self) -> bool:
        """Does this row assert an official taxonomy topic?"""
        return bool(self.topic) and self.assignment in self.OFFICIAL_ASSIGNMENTS

    @property
    def leaf(self) -> str:
        if not self.topic:
            return ''
        return f'{self.topic}/{self.subcategory}' if self.subcategory else self.topic

    @property
    def label(self) -> str:
        """Human-readable name, resolved against the live taxonomy."""
        from reasoning.taxonomy import subcategory_label, topic_label
        if not self.topic:
            return self.model_concept or 'Unclassified'
        if self.subcategory:
            return (f'{topic_label(self.topic)} / '
                    f'{subcategory_label(self.topic, self.subcategory)}')
        return topic_label(self.topic)

    @property
    def is_stale(self) -> bool:
        """Was this written under a taxonomy whose changes may have invalidated it?

        Uses the Phase 0 lineage, so a purely ADDITIVE taxonomy change leaves
        existing assignments valid-but-incomplete rather than marking the whole
        corpus stale and forcing a full reclassification.
        """
        from reasoning.taxonomy import tags_still_valid_since
        return not tags_still_valid_since(self.taxonomy_version)


# ── TopicSuggestion — the human-controlled route to taxonomy growth ──────────

class TopicSuggestion(models.Model):
    """A proposed addition to the official taxonomy, awaiting human judgement.

    The taxonomy is human-governed. A model may notice that no official topic
    represents something it judges important, but noticing is the limit of its
    authority: nothing in this model, in any view, or in any management command
    writes to reasoning/taxonomy.py. A suggestion is a REQUEST, and the gap
    between requesting and being official is deliberate and unbridgeable by
    code.

    The lifecycle encodes that gap:

        suggested ── under_review ─┬─ approved_pending_release ── active
                                   ├─ rejected
                                   ├─ merged      (into an official topic, or
                                   │               into another suggestion)
                                   └─ superseded

    APPROVED_PENDING_RELEASE IS NOT OFFICIAL. It records that a human decided
    the concept deserves to exist. The topic becomes real only when a person
    edits TAXONOMY in source and commits it — at which point the fingerprint
    changes and `mark_active()` can verify the topic is genuinely there.
    `mark_active()` REFUSES if it is not, so the two states cannot drift.

    Suggestions are also deliberately hard to create. A concept reaches here
    only after resolve_concept() has failed to match it against the official
    vocabulary, its aliases, and every open suggestion — see
    apps.library.suggestions. Without that filtering, "storage limitation",
    "data retention" and "data storage period" would become three proposals
    for a topic the taxonomy already has.
    """

    SUGGESTED                = 'suggested'
    UNDER_REVIEW             = 'under_review'
    APPROVED_PENDING_RELEASE = 'approved_pending_release'
    ACTIVE                   = 'active'
    REJECTED                 = 'rejected'
    MERGED                   = 'merged'
    SUPERSEDED               = 'superseded'
    STATUS_CHOICES = [
        (SUGGESTED, 'Suggested'),
        (UNDER_REVIEW, 'Under review'),
        (APPROVED_PENDING_RELEASE, 'Approved — pending taxonomy release'),
        (ACTIVE, 'Active (in the official taxonomy)'),
        (REJECTED, 'Rejected'),
        (MERGED, 'Merged'),
        (SUPERSEDED, 'Superseded'),
    ]
    OPEN_STATUSES     = (SUGGESTED, UNDER_REVIEW)
    TERMINAL_STATUSES = (ACTIVE, REJECTED, MERGED, SUPERSEDED)

    MODEL = 'model'
    HUMAN = 'human'
    ORIGIN_CHOICES = [(MODEL, 'Proposed by the model'),
                      (HUMAN, 'Proposed by a person')]

    proposed_name       = models.CharField(max_length=120)
    # Normalised identifier the topic would take in TAXONOMY. Unique among
    # non-terminal suggestions so the same idea cannot be filed twice.
    proposed_slug       = models.CharField(max_length=64, db_index=True)
    proposed_subcategory = models.CharField(max_length=64, blank=True)
    # '' proposes a new TOP-LEVEL topic; an official tag proposes a new
    # subcategory beneath it. Both are legitimate — the taxonomy grows in
    # either direction, and a new subcategory is usually the cheaper answer.
    parent_topic        = models.CharField(max_length=64, blank=True, db_index=True)

    reason              = models.TextField(blank=True)
    why_existing_insufficient = models.TextField(blank=True)
    # Highest confidence seen across this suggestion's evidence. Not an
    # average: one strong observation matters more than many weak ones.
    confidence          = models.FloatField(default=0.0)
    # Denormalised count of evidence rows, kept in step by the service. A
    # count is NOT a mandate — a repeatedly-observed concept is worth a
    # reviewer's attention, not automatic promotion.
    occurrence_count    = models.PositiveIntegerField(default=0, db_index=True)
    # [{topic, subcategory, score, label}] — what the resolver nearly matched.
    # Shown to the reviewer so "this is really an existing topic" is an easy
    # call to make, which is the outcome we WANT most of the time.
    similar_topics      = models.JSONField(default=list, blank=True)

    status              = models.CharField(max_length=26, choices=STATUS_CHOICES,
                                           default=SUGGESTED, db_index=True)
    origin              = models.CharField(max_length=8, choices=ORIGIN_CHOICES,
                                           default=MODEL, db_index=True)

    # Set when a reviewer decides this is really an existing official topic.
    merged_into_topic   = models.CharField(max_length=64, blank=True)
    merged_into_subcategory = models.CharField(max_length=64, blank=True)
    # Set when two proposals turn out to be the same idea.
    merged_into_suggestion = models.ForeignKey('self', null=True, blank=True,
                                               on_delete=models.SET_NULL,
                                               related_name='merged_from')

    reviewer            = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                            blank=True, on_delete=models.SET_NULL)
    reviewed_at         = models.DateTimeField(null=True, blank=True)
    reviewer_note       = models.TextField(blank=True)

    # The exact source change a human would have to commit for this to become
    # official. GENERATED, never applied — see apps.library.suggestions.
    proposed_patch      = models.TextField(blank=True)

    taxonomy_version_at_suggestion = models.CharField(max_length=32, blank=True)
    # The fingerprint the taxonomy is expected to carry once the patch lands.
    # Lets mark_active() confirm the release actually happened.
    expected_taxonomy_version = models.CharField(max_length=32, blank=True)

    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-occurrence_count', '-confidence', 'proposed_name']
        constraints = [
            # One OPEN proposal per slug. Terminal rows are excluded so a
            # rejected idea can be raised again later with fresh evidence —
            # rejection is a judgement on what was known then, not forever.
            models.UniqueConstraint(
                fields=['proposed_slug'],
                condition=models.Q(status__in=('suggested', 'under_review',
                                               'approved_pending_release')),
                name='uniq_open_topic_suggestion_slug'),
        ]
        indexes = [models.Index(fields=['status', '-occurrence_count'])]

    def __str__(self):
        return f'{self.proposed_name} ({self.status})'

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    @property
    def is_official(self) -> bool:
        """Is this an actual entry in the official taxonomy RIGHT NOW?

        Deliberately answered by reading reasoning/taxonomy.py rather than by
        trusting `status`. The database cannot make a topic official; only the
        source file can, so the source file is what gets asked.
        """
        from reasoning.taxonomy import is_valid
        if self.status != self.ACTIVE:
            return False
        return is_valid(self.parent_topic or self.proposed_slug,
                        self.proposed_subcategory or None)

    @property
    def target_leaf(self) -> str:
        """The leaf this suggestion would add, as 'topic/subcategory'."""
        if self.parent_topic:
            return f'{self.parent_topic}/{self.proposed_subcategory or self.proposed_slug}'
        if self.proposed_subcategory:
            return f'{self.proposed_slug}/{self.proposed_subcategory}'
        return self.proposed_slug

    @property
    def awaiting_release(self) -> bool:
        return self.status == self.APPROVED_PENDING_RELEASE


class TopicSuggestionEvidence(models.Model):
    """One observation supporting a suggestion, traceable to real source text.

    Evidence is what turns "the model said a word" into something a reviewer
    can actually judge. Each row points at the requirement that raised the
    concept and carries the quote it came from, so the reviewer reads the law
    rather than the model's summary of it.

    Nothing here is generated: `quote` must come from the requirement or its
    source provision. A suggestion whose evidence cannot be traced to real
    text is a suggestion that should be rejected.
    """
    suggestion    = models.ForeignKey(TopicSuggestion, on_delete=models.CASCADE,
                                      related_name='evidence')
    requirement   = models.ForeignKey('library.Requirement', null=True, blank=True,
                                      on_delete=models.CASCADE,
                                      related_name='topic_suggestion_evidence')
    # Kept as a loose id rather than an FK: chunks live in the sqlite search
    # store, not in Django, and the same idiom is already used by
    # ObligationMapping.regulation_chunk_id and FeedbackSignal.source_id.
    chunk_node_id = models.CharField(max_length=64, blank=True, db_index=True)

    # The model's ORIGINAL wording for this observation. Two evidence rows on
    # one suggestion may carry different wordings — that IS the dedup working.
    model_concept = models.CharField(max_length=200, blank=True)
    quote         = models.TextField(blank=True)
    confidence    = models.FloatField(default=0.0)

    taxonomy_version = models.CharField(max_length=32, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-confidence', 'id']
        constraints = [
            # One observation per requirement per wording, so re-running
            # classification accumulates evidence without inflating the count.
            models.UniqueConstraint(
                fields=['suggestion', 'requirement', 'model_concept'],
                name='uniq_evidence_per_requirement_concept'),
        ]

    def __str__(self):
        return f'{self.model_concept} @ req#{self.requirement_id}'
