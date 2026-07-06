from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Per-user profile holding the RBAC role.

    Default Django User is kept as-is; this OneToOne sidecar adds the role
    field plus future per-user MFA/security flags without forcing an
    AUTH_USER_MODEL swap.
    """

    ANALYST  = 'analyst'
    REVIEWER = 'reviewer'
    ADMIN    = 'admin'
    ROLE_CHOICES = [
        (ANALYST,  'Compliance Analyst'),
        (REVIEWER, 'Legal Reviewer'),
        (ADMIN,    'Administrator'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default=ANALYST,
    )
    require_mfa_setup = models.BooleanField(default=True)
    # set to True when the user has a temp password (just created or reset
    # by an admin). middleware redirects them to /accounts/password_change/
    # until they change it. cleared once the change goes through.
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f'{self.user.username} ({self.get_role_display()})'

    @property
    def is_analyst(self):
        return self.role == self.ANALYST

    @property
    def is_reviewer(self):
        return self.role == self.REVIEWER

    @property
    def is_admin(self):
        return self.role == self.ADMIN
