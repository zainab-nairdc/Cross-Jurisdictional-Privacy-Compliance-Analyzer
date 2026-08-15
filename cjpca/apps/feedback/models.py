"""RAG feedback loop — data model (feasibility).

Two tables close the loop:

  FeedbackSignal — one row per reviewer decision (accept / reject / modify) on an
                   AI-produced result. This is the raw *labelled* data the loop
                   runs on: what the model said, what the human decided, when, and
                   under which taxonomy/model version.

  GoldExemplar   — a reviewer-APPROVED result promoted to a reusable exemplar.
                   Retrieved as few-shot context on future runs of the same topic
                   so the model is steered by what humans have already blessed.
                   Only APPROVED content enters the gold set (governance: raw votes
                   never change behaviour — approvals do).

Both are version-stamped (taxonomy_version / model_version) so feedback gathered
under one configuration is scoped out when the taxonomy or model changes. The
stamps are ENFORCED at scoring time by services.chunk_feedback_scores(): stale
rows are ignored for retrieval but never deleted, so they stay queryable for
audit and history.

Signal kinds and what each one currently DOES:
    approve -> +1 retrieval signal on the row's chunks, and promotes to GoldExemplar
    reject  -> -1 retrieval signal on the row's chunks
    modify  -> +0.5 retrieval signal on the row's chunks (bounded positive boost
              so the corrected clause surfaces more reliably).
"""

from django.conf import settings
from django.db import models


class FeedbackSignal(models.Model):
    APPROVE = 'approve'
    REJECT  = 'reject'
    MODIFY  = 'modify'
    KIND_CHOICES = [(APPROVE, 'Approve'), (REJECT, 'Reject'), (MODIFY, 'Modify')]

    kind        = models.CharField(max_length=12, choices=KIND_CHOICES, db_index=True)
    # Loose link (not a hard FK) so the same signal table serves comparison rows
    # now and mapping/coverage rows later without a schema change.
    source_app  = models.CharField(max_length=40, default='comparison', db_index=True)
    source_id   = models.PositiveIntegerField(db_index=True)          # e.g. ComparisonResult.pk
    topic       = models.CharField(max_length=120, blank=True, db_index=True)
    query       = models.TextField(blank=True)                       # what was compared / asked
    before      = models.JSONField(default=dict, blank=True)         # the AI's version
    after       = models.JSONField(default=dict, blank=True)         # reviewer's corrected version (modify)
    note        = models.TextField(blank=True)
    actor       = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL)
    taxonomy_version = models.CharField(max_length=40, blank=True)
    model_version    = models.CharField(max_length=60, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.kind} on {self.source_app}#{self.source_id} ({self.topic})'


class GoldExemplar(models.Model):
    """An approved result promoted to a reusable few-shot exemplar."""
    topic        = models.CharField(max_length=120, db_index=True)
    query        = models.TextField(blank=True)
    reg_a        = models.CharField(max_length=160, blank=True)
    reg_b        = models.CharField(max_length=160, blank=True)
    payload      = models.JSONField(default=dict)                    # approved obligation snapshot
    approved_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL)
    source_id    = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    taxonomy_version = models.CharField(max_length=40, blank=True)
    active       = models.BooleanField(default=True, db_index=True)
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'gold[{self.topic}] {self.reg_a} ↔ {self.reg_b}'
