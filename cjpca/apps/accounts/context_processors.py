"""Template context processor.

PoC build: roles are removed, so every authenticated user has full access.
The ``is_analyst`` / ``is_reviewer`` / ``is_admin`` flags are kept (all True)
only so the existing templates that branch on them still render every
feature. ``user_role`` is exposed as a neutral label used by a couple of
templates to decide which action buttons to show.
"""


def user_role(request):
    user = getattr(request, 'user', None)
    authed = bool(user and user.is_authenticated)
    return {
        'user_role':   'analyst' if authed else None,
        'is_analyst':  authed,
        'is_reviewer': authed,
        'is_admin':    authed,
    }
