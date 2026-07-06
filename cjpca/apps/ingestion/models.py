from django.conf import settings
from django.db import models

STAGE_NAMES = {1: 'Upload', 2: 'Parse', 3: 'Chunk', 4: 'Embed', 5: 'Index', 6: 'Ready'}


class QuarantinedChunk(models.Model):
    """A chunk diverted from the ingestion pipeline by the prompt-injection scanner.

    The scanner runs after the chunker and before the embedder
    (apps.ingestion.pipeline). Any chunk that trips a Tier A regex or the
    Tier B Ollama judge is persisted here instead of being indexed into
    Chroma + BM25. An admin reviews it and either approves (release into
    the index) or rejects (drop permanently).

    This table is the audit trail for the defense-in-depth claim: every
    detection is a row, every admin decision is a row update, and the
    paired AuditLog entry ties the action to a user.
    """

    PENDING  = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    STATUS_CHOICES = [
        (PENDING,  'Pending review'),
        (APPROVED, 'Approved (released to index)'),
        (REJECTED, 'Rejected (permanently quarantined)'),
    ]

    SEVERITY_HIGH   = 'high'
    SEVERITY_MEDIUM = 'medium'
    SEVERITY_CHOICES = [
        (SEVERITY_HIGH,   'High'),
        (SEVERITY_MEDIUM, 'Medium'),
    ]

    TIER_A = 'A'
    TIER_B = 'B'
    TIER_CHOICES = [
        (TIER_A, 'Tier A — regex catalog'),
        (TIER_B, 'Tier B — LLM judge'),
    ]

    job          = models.ForeignKey('ingestion.IngestionJob',
                                     null=True, blank=True,
                                     on_delete=models.SET_NULL,
                                     related_name='quarantined_chunks')
    document     = models.ForeignKey('library.Document', on_delete=models.CASCADE,
                                     related_name='quarantined_chunks')
    chunk_index  = models.PositiveIntegerField(default=0)
    node_id      = models.CharField(max_length=64, blank=True, db_index=True)
    section_title = models.CharField(max_length=255, blank=True)
    content      = models.TextField()
    rule_id      = models.CharField(max_length=40, db_index=True)
    severity     = models.CharField(max_length=10, choices=SEVERITY_CHOICES,
                                    default=SEVERITY_HIGH, db_index=True)
    tier         = models.CharField(max_length=1, choices=TIER_CHOICES, default=TIER_A)
    rule_description = models.CharField(max_length=255, blank=True)
    matched_snippet  = models.TextField(blank=True)
    judge_reason     = models.TextField(blank=True)
    # All detections fired against this chunk (rule_id → snippet pairs), so
    # the admin sees the full picture, not just the first match.
    all_detections   = models.JSONField(default=list)

    status       = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                    default=PENDING, db_index=True)
    decided_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='quarantine_decisions',
    )
    decided_at   = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    chunk_metadata = models.JSONField(default=dict)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['severity', '-created_at']),
        ]

    def __str__(self):
        return f'[{self.severity.upper()}] {self.rule_id} on {self.document.name} #{self.chunk_index}'


class IngestionJob(models.Model):
    QUEUED   = 'queued'
    RUNNING  = 'running'
    COMPLETE = 'complete'
    FAILED   = 'failed'
    STATUS_CHOICES = [
        (QUEUED,   'Queued'),
        (RUNNING,  'Running'),
        (COMPLETE, 'Complete'),
        (FAILED,   'Failed'),
    ]

    document      = models.ForeignKey('library.Document', on_delete=models.CASCADE,
                                      related_name='ingestion_jobs')
    current_stage = models.PositiveSmallIntegerField(default=1)   # 1–6
    progress_pct  = models.PositiveSmallIntegerField(default=0)
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, default=QUEUED,
                                     db_index=True)
    error_message = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    log_entries   = models.JSONField(default=list)
    # Who triggered this ingestion. Set by the upload view; null for jobs
    # created from CLI/management commands or for legacy rows that pre-date
    # this column. Used by apps.notifications to route the
    # ingestion.complete / ingestion.failed in-app message to the admin who
    # uploaded the document.
    created_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='triggered_ingestion_jobs',
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.document.name} — Stage {self.current_stage}/6'

    @property
    def stage_name(self):
        return STAGE_NAMES.get(self.current_stage, 'Unknown')

    @property
    def is_active(self):
        return self.status in (self.QUEUED, self.RUNNING)
