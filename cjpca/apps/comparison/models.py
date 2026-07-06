from django.conf import settings
from django.db import models

# ── V1 Models (kept for backward compat) ──────────────────────────────────────

class ComparisonAnalysis(models.Model):
    DRAFT    = 'draft'
    COMPLETE = 'complete'
    STATUS_CHOICES = [(DRAFT, 'Draft'), (COMPLETE, 'Complete')]

    reg_a      = models.ForeignKey('library.Document', on_delete=models.CASCADE,
                                   related_name='comparisons_as_a')
    reg_b      = models.ForeignKey('library.Document', on_delete=models.CASCADE,
                                   related_name='comparisons_as_b')
    topic      = models.CharField(max_length=100)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'comparison analyses'

    def __str__(self):
        return f'{self.reg_a.name} vs {self.reg_b.name} — {self.topic}'


class ClausePair(models.Model):
    EQUIVALENT = 'equivalent'
    PARTIAL    = 'partial'
    SIMILAR    = 'similar'
    NONE       = 'none'
    MATCH_CHOICES = [
        (EQUIVALENT, 'Equivalent'),
        (PARTIAL,    'Partial'),
        (SIMILAR,    'Similar'),
        (NONE,       'No match'),
    ]

    analysis         = models.ForeignKey(ComparisonAnalysis, on_delete=models.CASCADE,
                                         related_name='clause_pairs')
    reg_a_article    = models.CharField(max_length=50)
    reg_b_article    = models.CharField(max_length=50, blank=True)
    match_type       = models.CharField(max_length=20, choices=MATCH_CHOICES, default=NONE)
    similarity_score = models.FloatField(default=0.0)
    ai_analysis      = models.TextField(blank=True)

    def __str__(self):
        return f'{self.reg_a_article} ↔ {self.reg_b_article} ({self.match_type})'


# ── V2 Constants ───────────────────────────────────────────────────────────────

PAIR_CONFIGS = {
    'bh_in': {'a': 'bahrain', 'b': 'india',  'label': 'Bahrain PDPL ↔ India DPDPA',  'code_a': 'BH', 'code_b': 'IN', 'flag_a': '🇧🇭', 'flag_b': '🇮🇳'},
    'bh_kw': {'a': 'bahrain', 'b': 'kuwait', 'label': 'Bahrain PDPL ↔ Kuwait DPPR',  'code_a': 'BH', 'code_b': 'KW', 'flag_a': '🇧🇭', 'flag_b': '🇰🇼'},
    'in_kw': {'a': 'india',   'b': 'kuwait', 'label': 'India DPDPA ↔ Kuwait DPPR',   'code_a': 'IN', 'code_b': 'KW', 'flag_a': '🇮🇳', 'flag_b': '🇰🇼'},
}

REL_COLORS = {
    'equivalent':      '#3FB85C',   # green — aligned
    'stricter_in_a':   '#002583',   # navy — side A wins
    'stricter_in_b':   '#FFB800',   # amber — side B wins
    'additional_in_a': '#5A6BBE',   # muted navy — only-in-A
    'additional_in_b': '#E5B45F',   # muted amber — only-in-B
    'conflicting':     '#D93939',   # red — flag for legal review
}

REL_LABELS = {
    'equivalent':      'Equivalent',
    'stricter_in_a':   'Stricter in A',
    'stricter_in_b':   'Stricter in B',
    'additional_in_a': 'Additional in A',
    'additional_in_b': 'Additional in B',
    'conflicting':     'Conflicting',
}

REL_BG = {
    'equivalent':      '#E5E8EF',
    'stricter_in_a':   '#E5E8EF',
    'stricter_in_b':   '#E5E8EF',
    'additional_in_a': '#E5E8EF',
    'additional_in_b': '#E5E8EF',
    'conflicting':     '#E5E8EF',
}


# ── V2 Models ──────────────────────────────────────────────────────────────────

class ComparisonRun(models.Model):
    PENDING          = 'pending'
    RUNNING          = 'running'
    COMPLETE         = 'complete'
    FAILED           = 'failed'
    PARTIALLY_FAILED = 'partially_failed'
    STATUS_CHOICES   = [
        (PENDING,          'Pending'),
        (RUNNING,          'Running'),
        (COMPLETE,         'Complete'),
        (FAILED,           'Failed'),
        (PARTIALLY_FAILED, 'Partially failed'),
    ]

    pair_key        = models.CharField(max_length=10, db_index=True)
    reg_a           = models.ForeignKey('library.Document', on_delete=models.CASCADE,
                                        related_name='runs_as_a')
    reg_b           = models.ForeignKey('library.Document', on_delete=models.CASCADE,
                                        related_name='runs_as_b')
    topics          = models.JSONField(default=list)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING,
                                       db_index=True)
    completed_pairs = models.PositiveIntegerField(default=0)
    total_pairs     = models.PositiveIntegerField(default=0)
    error_message   = models.TextField(blank=True)
    # Full reasoning-layer output dumped as JSON so the workspace can rebuild
    # the rich obligation view without losing fields (procedural/substantive/
    # enforcement strictness axes, raw equivalence, etc.) that don't have
    # dedicated columns on ComparisonResult. Optional — older runs have None.
    report_json     = models.JSONField(default=dict, blank=True)
    # Analyst handoff to reviewer. When `submitted_for_review_at` is set, the
    # run shows up on the reviewer's queue and the workspace switches its
    # "Send to reviewer" button to a status pill. analyst_note captures the
    # one-liner the analyst added at handoff (optional). Set together via the
    # /comparison/runs/<pk>/submit-review/ endpoint.
    analyst_note            = models.TextField(blank=True)
    submitted_for_review_at = models.DateTimeField(null=True, blank=True)
    submitted_by            = models.ForeignKey(settings.AUTH_USER_MODEL,
                                                null=True, blank=True,
                                                on_delete=models.SET_NULL,
                                                related_name='submitted_comparison_runs')
    created_at      = models.DateTimeField(auto_now_add=True)
    created_by      = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.reg_a.name} vs {self.reg_b.name}'

    @property
    def progress_pct(self):
        if not self.total_pairs:
            return 0
        return round(self.completed_pairs / self.total_pairs * 100)

    @property
    def pair_label(self):
        return PAIR_CONFIGS.get(self.pair_key, {}).get('label', f'{self.reg_a.name} ↔ {self.reg_b.name}')

    @property
    def topics_display(self):
        if not self.topics:
            return 'All topics'
        return ', '.join(t.replace('_', ' ').title() for t in self.topics)


class ComparisonResult(models.Model):
    EQUIVALENT      = 'equivalent'
    STRICTER_IN_A   = 'stricter_in_a'
    STRICTER_IN_B   = 'stricter_in_b'
    ADDITIONAL_IN_A = 'additional_in_a'
    ADDITIONAL_IN_B = 'additional_in_b'
    CONFLICTING     = 'conflicting'
    RELATIONSHIP_CHOICES = [
        (EQUIVALENT,      'Equivalent'),
        (STRICTER_IN_A,   'Stricter in A'),
        (STRICTER_IN_B,   'Stricter in B'),
        (ADDITIONAL_IN_A, 'Additional in A'),
        (ADDITIONAL_IN_B, 'Additional in B'),
        (CONFLICTING,     'Conflicting'),
    ]

    DRAFT    = 'draft'
    REVIEWED = 'reviewed'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    LIFECYCLE_CHOICES = [
        (DRAFT,    'Draft'),
        (REVIEWED, 'Reviewed'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    ]

    run              = models.ForeignKey(ComparisonRun, on_delete=models.CASCADE,
                                         related_name='results')
    citation_a       = models.CharField(max_length=200)
    citation_b       = models.CharField(max_length=200, blank=True)
    preview_a        = models.TextField(blank=True)
    preview_b        = models.TextField(blank=True)
    clause_text_a    = models.TextField(blank=True)
    clause_text_b    = models.TextField(blank=True)
    relationship     = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES,
                                        default=EQUIVALENT, db_index=True)
    confidence       = models.FloatField(default=0.0)
    similarity_score = models.FloatField(default=0.0)
    rationale        = models.TextField(blank=True)
    key_difference   = models.TextField(blank=True)
    lifecycle        = models.CharField(max_length=20, choices=LIFECYCLE_CHOICES, default=DRAFT,
                                        db_index=True)
    reviewer_note    = models.TextField(blank=True)
    principle_ids    = models.JSONField(default=list)
    citation_verified = models.BooleanField(default=True)
    # populated by reasoning.workflows.compare_regulations() — gives the UI
    # the verbatim quote that grounds each row, the chunk node_id for deep-
    # linking to the document viewer, and an NLI hallucination risk in [0,1].
    # blank/0 on legacy rows that pre-date the reasoning-layer migration.
    evidence_a       = models.TextField(blank=True)
    evidence_b       = models.TextField(blank=True)
    chunk_id_a       = models.CharField(max_length=64, blank=True, db_index=True)
    chunk_id_b       = models.CharField(max_length=64, blank=True, db_index=True)
    hallucination_risk = models.FloatField(default=0.0)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        b = self.citation_b or '—'
        return f'{self.citation_a} ↔ {b} ({self.relationship})'

    @property
    def confidence_pct(self):
        return round(self.confidence * 100)

    @property
    def similarity_pct(self):
        return round(self.similarity_score * 100)

    @property
    def rel_color(self):
        return REL_COLORS.get(self.relationship, '#D1D5E0')

    @property
    def rel_bg(self):
        return REL_BG.get(self.relationship, '#E5E8EF')

    @property
    def rel_label(self):
        return REL_LABELS.get(self.relationship, self.relationship)

    @property
    def is_orphan(self):
        return self.relationship in (self.ADDITIONAL_IN_A, self.ADDITIONAL_IN_B)


class AuditEvent(models.Model):
    result         = models.ForeignKey(ComparisonResult, on_delete=models.CASCADE,
                                       related_name='audit_events')
    actor          = models.CharField(max_length=100, default='system')
    action         = models.CharField(max_length=50, db_index=True)
    from_lifecycle = models.CharField(max_length=20, blank=True)
    to_lifecycle   = models.CharField(max_length=20, blank=True)
    diff           = models.JSONField(null=True, blank=True)
    timestamp      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f'{self.actor} {self.action} result #{self.result_id}'
