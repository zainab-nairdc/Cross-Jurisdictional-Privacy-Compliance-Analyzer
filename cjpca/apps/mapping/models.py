from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


# ── MappingAnalysis (V2 — extended) ──────────────────────────────────────────

class MappingAnalysis(models.Model):
    QUEUED    = 'queued'
    RUNNING   = 'running'
    COMPLETE  = 'complete'
    FAILED    = 'failed'
    CANCELLED = 'cancelled'
    REVIEW    = 'review'
    APPROVED  = 'approved'
    STATUS_CHOICES = [
        (QUEUED,    'Queued'),
        (RUNNING,   'Running'),
        (COMPLETE,  'Complete'),
        (FAILED,    'Failed'),
        (CANCELLED, 'Cancelled'),
        (REVIEW,    'In Review'),
        (APPROVED,  'Approved'),
    ]

    # SCOPE_AUTO is the methodologically correct default: classify the policy
    # first, then map only against topics the policy actually covers AND the
    # target jurisdiction has classified clauses for. SCOPE_FULL/TOPICS remain
    # available for users who want the older naive behaviour.
    SCOPE_AUTO     = 'auto'
    SCOPE_FULL     = 'full'
    SCOPE_TOPICS   = 'topics'
    SCOPE_SPECIFIC = 'specific'
    SCOPE_CHOICES  = [
        (SCOPE_AUTO,     'Auto-route from policy'),
        (SCOPE_FULL,     'All topics'),
        (SCOPE_TOPICS,   'Selected topics'),
        (SCOPE_SPECIFIC, 'Specific articles'),
    ]

    policy_doc               = models.ForeignKey('library.Document', on_delete=models.CASCADE,
                                                  related_name='mapping_analyses')
    regulations              = models.ManyToManyField('library.Document',
                                                      related_name='mappings_against', blank=True)
    # V1 compat
    topic                    = models.CharField(max_length=255, blank=True)
    # V2 scope
    scope_mode               = models.CharField(max_length=20, choices=SCOPE_CHOICES,
                                                default=SCOPE_FULL)
    scope_topics             = models.JSONField(default=list, blank=True)
    scope_article_ids        = models.JSONField(default=list, blank=True)
    include_asymmetric       = models.BooleanField(default=False)
    # Topics the policy covers but NO in-scope regulation legislates on. Stored
    # as [{topic, label, policy_chunks}] and rendered as "skipped" — explicitly
    # NOT gaps. Kept separate from gap_count so a topic no law addresses can
    # never be mistaken for a compliance failure.
    skipped_topics           = models.JSONField(default=list, blank=True)

    status                   = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                                default=QUEUED, db_index=True)
    progress_current         = models.PositiveIntegerField(default=0)
    progress_total           = models.PositiveIntegerField(default=0)
    current_obligation_label = models.CharField(max_length=300, blank=True)

    obligation_count         = models.PositiveIntegerField(default=0)
    gap_count                = models.PositiveIntegerField(default=0)
    error                    = models.TextField(blank=True)

    run_at                   = models.DateTimeField(auto_now_add=True)
    completed_at             = models.DateTimeField(null=True, blank=True)
    cancelled_at             = models.DateTimeField(null=True, blank=True)
    created_by               = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                                  on_delete=models.SET_NULL)

    # Analyst handoff to reviewer — same shape as ComparisonRun. When set, the
    # analysis shows on the reviewer queue with the analyst's optional note;
    # the workspace's "Send to reviewer" button flips to a status pill.
    analyst_note             = models.TextField(blank=True)
    submitted_for_review_at  = models.DateTimeField(null=True, blank=True)
    submitted_by             = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='submitted_mapping_analyses',
    )

    class Meta:
        ordering = ['-run_at']
        verbose_name_plural = 'mapping analyses'

    def __str__(self):
        return f'{self.policy_doc.name} mapping'

    @property
    def progress_pct(self):
        if not self.progress_total:
            return 0
        return round(self.progress_current / self.progress_total * 100)

    @property
    def reg_names(self):
        return ', '.join(r.name for r in self.regulations.all())


# ── ObligationMapping (V2 — extended) ────────────────────────────────────────

class ObligationMapping(models.Model):
    COVERED  = 'covered'
    PARTIAL  = 'partial'
    REVIEW   = 'review'
    NONE     = 'none'
    COVERAGE_CHOICES = [
        (COVERED, 'Covered'),
        (PARTIAL, 'Partial'),
        (REVIEW,  'Requires Review'),
        (NONE,    'Not Covered'),
    ]

    DRAFT    = 'draft'
    REVIEWED = 'reviewed'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    MODIFIED = 'modified'
    LIFECYCLE_CHOICES = [
        (DRAFT,    'Draft'),
        (REVIEWED, 'Reviewed'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
        (MODIFIED, 'Modified'),
    ]

    CRITICAL = 'critical'
    HIGH     = 'high'
    MEDIUM   = 'medium'
    LOW      = 'low'
    SEVERITY_CHOICES = [
        (CRITICAL, 'Critical'),
        (HIGH,     'High'),
        (MEDIUM,   'Medium'),
        (LOW,      'Low'),
    ]

    analysis          = models.ForeignKey(MappingAnalysis, on_delete=models.CASCADE,
                                          related_name='obligation_mappings')
    regulation        = models.ForeignKey('library.Document', on_delete=models.CASCADE)
    article_ref       = models.CharField(max_length=100)
    obligation_title  = models.CharField(max_length=300)
    obligation_text   = models.TextField(blank=True)

    coverage          = models.CharField(max_length=20, choices=COVERAGE_CHOICES, default=NONE,
                                          db_index=True)
    confidence        = models.FloatField(default=0.0)          # 0.0–1.0
    severity          = models.CharField(max_length=10, choices=SEVERITY_CHOICES,
                                         null=True, blank=True)

    evidence_text     = models.TextField(blank=True)        # policy-side excerpt
    evidence_source   = models.CharField(max_length=300, blank=True)
    # reasoning-layer grounding fields (populated by reasoning.workflows.map_policy_coverage).
    # regulation_evidence is the verbatim quote from the regulatory chunk that the
    # row is grounded in; regulation_chunk_id / policy_chunk_id are node_ids for
    # deep-linking to the document viewer with highlight; hallucination_risk is the
    # NLI score (0=grounded, 1=unsupported); citation_verified is the structural
    # check from workflow_helpers.verify_simple_citations. blank/0 on legacy rows.
    regulation_evidence = models.TextField(blank=True)
    regulation_chunk_id = models.CharField(max_length=64, blank=True, db_index=True)
    policy_chunk_id     = models.CharField(max_length=64, blank=True, db_index=True)
    citation_verified   = models.BooleanField(default=True)
    hallucination_risk  = models.FloatField(default=0.0)
    rationale         = models.TextField(blank=True)
    highlighted_phrases = models.JSONField(default=list)        # [{text, side, category}]
    topics            = models.JSONField(default=list)

    lifecycle         = models.CharField(max_length=20, choices=LIFECYCLE_CHOICES, default=DRAFT,
                                          db_index=True)
    reviewer_notes    = models.TextField(blank=True)
    human_override    = models.BooleanField(default=False)

    # V1 compat
    confidence_pct    = models.PositiveSmallIntegerField(default=0)

    completed_at      = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.article_ref} — {self.obligation_title} ({self.coverage})'

    @property
    def confidence_display(self):
        return round(self.confidence * 100)

    @property
    def is_gap(self):
        return self.coverage != self.COVERED

    @staticmethod
    def derive_severity(coverage: str, confidence: float) -> str | None:
        if coverage == ObligationMapping.COVERED:
            return None
        if coverage == ObligationMapping.NONE:
            return ObligationMapping.CRITICAL if confidence >= 0.85 else ObligationMapping.HIGH
        if coverage == ObligationMapping.PARTIAL:
            return ObligationMapping.HIGH if confidence >= 0.80 else ObligationMapping.MEDIUM
        if coverage == ObligationMapping.REVIEW:
            return ObligationMapping.MEDIUM if confidence >= 0.75 else ObligationMapping.LOW
        return ObligationMapping.LOW

    @property
    def risk(self) -> dict:
        """multi-factor risk breakdown — penalty × enforcement × impact × coverage_gap.
        full breakdown lives in apps.mapping.risk.compute_risk_score; templates
        access this via ``mapping.risk.score`` / ``mapping.risk.bucket`` /
        ``mapping.risk.explanation`` for tooltip display."""
        from .risk import compute_risk_score
        jur = self.regulation.jurisdiction if self.regulation_id else ''
        return compute_risk_score(
            jurisdiction = jur,
            coverage     = self.coverage,
            topics       = self.topics or [],
            confidence   = self.confidence,
        )


# ── Gap (V2 — extended) ──────────────────────────────────────────────────────

class Gap(models.Model):
    CRITICAL = 'critical'
    HIGH     = 'high'
    MEDIUM   = 'medium'
    LOW      = 'low'
    PRIORITY_CHOICES = [
        (CRITICAL, 'Critical'),
        (HIGH,     'High'),
        (MEDIUM,   'Medium'),
        (LOW,      'Low'),
    ]

    AI_DRAFTED  = 'ai_drafted'
    AI_EDITED   = 'ai_draft_edited'
    HUMAN       = 'human_written'
    REMEDIATION_SOURCE_CHOICES = [
        (AI_DRAFTED, 'AI Drafted'),
        (AI_EDITED,  'AI Draft Edited'),
        (HUMAN,      'Human Written'),
    ]
    # V1 compat aliases
    AI     = AI_DRAFTED
    EDITED = AI_EDITED

    mapping            = models.ForeignKey(MappingAnalysis, on_delete=models.CASCADE,
                                           related_name='gaps')
    obligation_mapping = models.OneToOneField(ObligationMapping, on_delete=models.CASCADE,
                                              related_name='gap')
    priority           = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=MEDIUM,
                                           db_index=True)
    severity           = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=MEDIUM)
    remediation_text   = models.TextField(blank=True)
    remediation_source = models.CharField(max_length=20, choices=REMEDIATION_SOURCE_CHOICES,
                                          default=AI_DRAFTED)
    # action assignment — who owns fixing this gap, by when. nullable so
    # legacy gaps stay valid; assignment is opt-in per gap. assigned_by is
    # tracked separately so we can show a notification breadcrumb in history.
    assigned_to        = models.ForeignKey(
                            'auth.User', on_delete=models.SET_NULL,
                            null=True, blank=True, related_name='assigned_gaps')
    assigned_by        = models.ForeignKey(
                            'auth.User', on_delete=models.SET_NULL,
                            null=True, blank=True, related_name='gaps_assigned')
    assigned_at        = models.DateTimeField(null=True, blank=True)
    due_date           = models.DateField(null=True, blank=True, db_index=True)
    created_at         = models.DateTimeField(auto_now_add=True)
    closed_at          = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Gap: {self.obligation_mapping.article_ref} ({self.priority})'

    @property
    def is_open(self):
        return self.closed_at is None

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone
        if not self.due_date or self.closed_at:
            return False
        return self.due_date < timezone.now().date()

    @property
    def days_to_due(self) -> int | None:
        from django.utils import timezone
        if not self.due_date:
            return None
        return (self.due_date - timezone.now().date()).days


# ── Auto-sync GapRecord on approval transition ────────────────────────────────

@receiver(post_save, sender=ObligationMapping)
def sync_gap_on_approval(sender, instance, **kwargs):
    if instance.lifecycle != ObligationMapping.APPROVED:
        return
    if instance.coverage == ObligationMapping.COVERED:
        Gap.objects.filter(obligation_mapping=instance).delete()
        return
    severity = instance.severity or ObligationMapping.derive_severity(
        instance.coverage, instance.confidence
    )
    Gap.objects.update_or_create(
        obligation_mapping=instance,
        defaults={
            'mapping':            instance.analysis,
            'priority':           severity or Gap.MEDIUM,
            'severity':           severity or Gap.MEDIUM,
            'remediation_text':   instance.rationale or '',
            'remediation_source': Gap.AI_DRAFTED,
        },
    )
