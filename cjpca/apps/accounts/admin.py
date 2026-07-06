from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ('user', 'role', 'require_mfa_setup', 'updated_at')
    list_filter   = ('role', 'require_mfa_setup')
    search_fields = ('user__username', 'user__email')
