"""Access-control primitives.

PoC build: role-based access control has been removed. Every authenticated
user can reach every page. ``role_required`` and ``RoleRequiredMixin`` are
kept as thin wrappers around Django's ``login_required`` so existing views
that reference them keep working without any role gating.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def get_user_role(user):
    """Return the user's profile role, or None. Retained only so the home
    dashboard can pick a default template; it no longer gates access."""
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    if profile is None:
        return None
    return profile.role


def role_required(*allowed_roles):
    """No-op role gate — requires login only (roles removed in the PoC)."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


class RoleRequiredMixin:
    """Class-based view mixin — requires login only (roles removed)."""

    allowed_roles: tuple = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)
