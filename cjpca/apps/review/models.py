from django.conf import settings
from django.db import models


class ReviewItem(models.Model):
    PENDING  = 'pending'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    MODIFIED = 'modified'
    STATUS_CHOICES = [
        (PENDING,  'Pending'),
        (ACCEPTED, 'Accepted'),
        (REJECTED, 'Rejected'),
        (MODIFIED, 'Modified'),
    ]

    mapping            = models.ForeignKey('mapping.MappingAnalysis', on_delete=models.CASCADE,
                                           related_name='review_items')
    obligation_mapping = models.ForeignKey('mapping.ObligationMapping', on_delete=models.CASCADE,
                                           related_name='review_items')
    status             = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    reviewer           = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.SET_NULL)
    reviewed_at        = models.DateTimeField(null=True, blank=True)
    reviewer_note      = models.TextField(blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.obligation_mapping.article_ref} — {self.status}'
