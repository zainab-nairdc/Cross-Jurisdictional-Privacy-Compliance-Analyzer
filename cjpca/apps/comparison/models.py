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
    """One execution of a regulation-to-regulation comparison.

    `status` is about EXECUTION (did the workflow finish?). `lifecycle` is about
    REVIEW (has a human signed this off as a compliance assessment?). They are
    orthogonal: a run can be `complete` and still `draft`, and that combination
    is the normal state of freshly generated output.

    An APPROVED run is a versioned compliance assessment, not a cached
    response. It records exactly which document versions were compared
    (`source_snapshot`), so the assessment can be judged against the sources it
    was actually based on rather than against whatever those documents happen
    to say today.
    """

    # ── status: execution ──
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

    # ── lifecycle: human review of the assessment as a whole ──
    # Distinct from ComparisonResult.lifecycle, which signs off ONE obligation
    # pair. Approving forty rows is not the same act as certifying the
    # assessment, and only the latter puts a run on the Approved Runs page.
    DRAFT      = 'draft'
    IN_REVIEW  = 'in_review'
    APPROVED   = 'approved'
    REJECTED   = 'rejected'
    SUPERSEDED = 'superseded'
    LIFECYCLE_CHOICES = [
        (DRAFT,      'Draft'),
        (IN_REVIEW,  'In review'),
        (APPROVED,   'Approved'),
        (REJECTED,   'Rejected'),
        (SUPERSEDED, 'Superseded by a newer approved version'),
    ]

    # ── currency: are the sources this was based on still what they were? ──
    # CURRENT  — the recorded snapshot still matches the live documents.
    # OUTDATED — a source has changed since approval. Detection lands in a
    #            later phase; the state exists now so nothing has to be
    #            inferred at render time.
    # UNKNOWN  — no verified snapshot was captured (every run that predates
    #            source-version tracking). NOT a synonym for current: it means
    #            currency cannot be established, and such a run must never be
    #            presented as current or offered for reuse.
    CURRENT  = 'current'
    OUTDATED = 'outdated'
    UNKNOWN  = 'unknown'
    CURRENCY_CHOICES = [
        (CURRENT,  'Current'),
        (OUTDATED, 'Outdated — a source has changed'),
        (UNKNOWN,  'Cannot verify currency'),
    ]

    # Was 10, which silently truncated on any backend that enforces length —
    # the live table already held 'bahrain_bahrain' (15 chars). Widened to fit
    # the jurisdiction-pair form this is actually written with.
    pair_key        = models.CharField(max_length=64, db_index=True)
    # PROTECT, not CASCADE. A comparison is only meaningful in terms of the two
    # documents it compared, so cascading would let a library tidy-up silently
    # destroy a signed-off compliance assessment — the exact audit failure this
    # model exists to prevent. Enforced at the ORM layer so a shell, a script or
    # the admin cannot bypass it either; the UI explains the refusal up front
    # via apps.comparison.assessments.deletion_blockers().
    reg_a           = models.ForeignKey('library.Document', on_delete=models.PROTECT,
                                        related_name='runs_as_a')
    reg_b           = models.ForeignKey('library.Document', on_delete=models.PROTECT,
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

    # ── Approved-assessment fields ──────────────────────────────────────────

    lifecycle       = models.CharField(max_length=12, choices=LIFECYCLE_CHOICES,
                                       default=DRAFT, db_index=True)
    approved_at     = models.DateTimeField(null=True, blank=True)
    approved_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.SET_NULL,
                                        related_name='approved_comparison_runs')

    # Stable identity of the QUESTION being asked, across every version of the
    # answer: (regulation A family, regulation B family, orientation, scope).
    #
    # Built from the version FAMILY root rather than the document pk, so
    # "Bahrain PDPL v1 vs India DPDP" and "Bahrain PDPL v2 vs India DPDP" are
    # two versions of ONE assessment — which is what makes v1/v2 lineage
    # meaningful.
    #
    # Orientation is part of it deliberately: A→B and B→A produce different
    # narratives, so they are different assessments, never two views of one.
    # Scope is part of it too, so a topic-scoped run cannot silently present
    # itself as a newer version of a full-scope one.
    assessment_key  = models.CharField(max_length=64, blank=True, db_index=True)

    # Position within the assessment. Assigned at APPROVAL, because only
    # approved runs are versions of an assessment — drafts and abandoned
    # experiments are not.
    version_no      = models.PositiveIntegerField(default=0)
    supersedes      = models.ForeignKey('self', null=True, blank=True,
                                        on_delete=models.SET_NULL,
                                        related_name='superseded_by_run')

    # Immutable record of exactly what was compared. Written once, at run
    # creation, and never updated — the moment it is rewritten it stops being
    # evidence of what the assessment was based on.
    source_snapshot = models.JSONField(default=dict, blank=True)
    # sha256 over the MATERIAL subset of the snapshot (documents + orientation
    # + scope). Empty means no verified capture: legacy runs carry '' and can
    # therefore never match a reuse lookup by accident.
    source_fingerprint = models.CharField(max_length=64, blank=True, db_index=True)

    currency_state     = models.CharField(max_length=10, choices=CURRENCY_CHOICES,
                                          default=UNKNOWN, db_index=True)
    outdated_reason    = models.CharField(max_length=300, blank=True)
    currency_checked_at = models.DateTimeField(null=True, blank=True)

    # What produced the analysis. Recorded for audit and displayed with the
    # assessment. Deliberately NOT part of source_fingerprint: a human approved
    # this OUTPUT, and swapping the model later does not retroactively
    # invalidate their judgement — only a change to the SOURCES does.
    model_version    = models.CharField(max_length=64, blank=True)
    prompt_version   = models.CharField(max_length=64, blank=True)
    taxonomy_version = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['lifecycle', '-approved_at']),
            models.Index(fields=['assessment_key', '-version_no']),
        ]

    def __str__(self):
        return f'{self.reg_a.name} vs {self.reg_b.name}'

    # ── approved-assessment helpers ─────────────────────────────────────────

    @property
    def is_approved(self) -> bool:
        return self.lifecycle == self.APPROVED

    @property
    def currency_is_verifiable(self) -> bool:
        """Was a real snapshot captured when this ran?

        False for every run that predates source-version tracking. Such a run
        may still be opened and audited, but nothing may claim it is current.
        """
        return bool(self.source_fingerprint) and not self.source_snapshot.get('backfilled')

    @property
    def is_reusable(self) -> bool:
        """May this assessment stand in for a fresh comparison?

        Approval alone is not enough — an approved assessment whose currency
        cannot be established is exactly the "silently use an outdated result
        as if it were current" failure this design exists to prevent.

        Reuse itself is not implemented yet; this is the gate the UI already
        uses to decide whether to OFFER it.
        """
        return (self.lifecycle == self.APPROVED
                and self.currency_state == self.CURRENT
                and self.currency_is_verifiable)

    @property
    def currency_label(self) -> str:
        if self.currency_state == self.CURRENT:
            return 'Current'
        if self.currency_state == self.OUTDATED:
            return self.outdated_reason or 'Outdated — a source has changed'
        return 'Cannot verify currency'

    @property
    def snapshot_a(self) -> dict:
        return (self.source_snapshot or {}).get('reg_a') or {}

    @property
    def snapshot_b(self) -> dict:
        return (self.source_snapshot or {}).get('reg_b') or {}

    @property
    def scope_label(self) -> str:
        scope = (self.source_snapshot or {}).get('scope') or {}
        if scope.get('mode') == 'topics' and scope.get('topics'):
            return f'{len(scope["topics"])} topic(s)'
        if self.topics:
            return f'{len(self.topics)} topic(s)'
        return 'Full scope'

    def review_state(self) -> dict:
        """How far the per-result review has got.

        Run-level approval is gated on this: every result must carry a human
        decision first. The two layers stay separate — this reads the
        per-result workflow, it does not replace it.
        """
        counts = {'total': 0, 'draft': 0, 'reviewed': 0,
                  'approved': 0, 'rejected': 0}
        for lifecycle in self.results.values_list('lifecycle', flat=True):
            counts['total'] += 1
            counts[lifecycle] = counts.get(lifecycle, 0) + 1
        counts['undecided'] = counts['draft']
        counts['all_decided'] = counts['total'] > 0 and counts['draft'] == 0
        return counts

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
    # ── Operational output — the "so what" for a compliance officer ────────────
    practical_conclusion = models.TextField(blank=True)                 # one actionable sentence
    compliance_impact    = models.CharField(max_length=40, blank=True)  # None | Minor | New control needed | Not Assessable
    shared_controls      = models.JSONField(default=list, blank=True)   # controls/policies satisfying BOTH
    terminology_note     = models.TextField(blank=True)                 # cross-term mapping
    created_at       = models.DateTimeField(auto_now_add=True)

    IMPACT_STYLES = {
        'none':               ('#1E7E48', '#E7F4EC', 'No new control required'),
        'minor':              ('#B86E00', '#FAEFD6', 'Minor additions'),
        'new control needed': ('#C0392B', '#FBE7E4', 'New control needed'),
    }

    @property
    def impact_style(self):
        """(color, bg, label) for the compliance-impact pill; falls back to neutral."""
        return self.IMPACT_STYLES.get((self.compliance_impact or '').strip().lower(),
                                      ('#5A6685', '#EEF1F8', self.compliance_impact or 'Not assessed'))

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
