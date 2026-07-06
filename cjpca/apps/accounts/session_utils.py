"""Session-management helpers.

``force_logout_user(user)`` — terminate every active Django session belonging
to a single user. Called from the user-management endpoints when an admin
changes someone's role, resets their MFA, disables their account, or resets
their password — anything that should invalidate stale privilege state on
that user's open browser tabs.

The implementation walks ``django.contrib.sessions.models.Session`` and
deletes rows whose decoded data carries the matching ``_auth_user_id``.
This is O(n) over total active sessions, which is fine at our scale —
under 100 users at BBK. If the session count grows materially we'd switch
to indexed user→session reverse lookups (e.g. django-user-sessions).
"""

from django.contrib.sessions.models import Session


def force_logout_user(user) -> int:
    """Delete every Session whose ``_auth_user_id`` matches ``user.pk``.

    Returns the number of sessions deleted. No-op if ``user`` is None or
    has no PK yet.
    """
    if user is None or not getattr(user, 'pk', None):
        return 0

    target_id = str(user.pk)
    deleted = 0
    for session in Session.objects.iterator():
        try:
            data = session.get_decoded()
        except Exception:
            # Corrupt session row — leave it alone, Django's clearsessions
            # management command will clean it up on the next cron run.
            continue
        if str(data.get('_auth_user_id', '')) == target_id:
            session.delete()
            deleted += 1
    return deleted
