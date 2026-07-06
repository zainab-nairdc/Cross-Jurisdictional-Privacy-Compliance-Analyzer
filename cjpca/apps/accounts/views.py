"""User management views — admin-only.

URLs:
    GET  /accounts/users/                       — list + filter
    POST /accounts/users/new/                   — create user
    POST /accounts/users/<pk>/role/             — change role
    POST /accounts/users/<pk>/disable/          — toggle is_active
    POST /accounts/users/<pk>/reset-password/   — set a temporary password
    POST /accounts/users/<pk>/reset-mfa/        — clear TOTP devices (Part B)
"""

import logging
import secrets
import string

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LogoutView, PasswordChangeView
from django.contrib.sessions.models import Session
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView
from django.views.decorators.http import require_GET


class GetAwareLogoutView(LogoutView):
    """LogoutView that accepts GET as well as POST.

    Django 5 restricted the built-in LogoutView to POST only. We still need
    GET for the idle-timeout flow: when the idle warning expires, the JS
    fires ``window.location.href = '/accounts/logout/?next=...'``, which is
    necessarily a GET. Adding GET back keeps that flow working without
    rewriting the client-side timer.

    POST-driven logouts (e.g. the profile widget's <form method="post">)
    keep working unchanged.
    """
    http_method_names = ['get', 'post', 'options']


class ForcedPasswordChangeView(PasswordChangeView):
    """drop-in replacement for django's auth_views.PasswordChangeView that
    also clears profile.must_change_password on successful change. wired
    at /accounts/password_change/ via apps.accounts.urls (mounted before
    django.contrib.auth.urls so this wins)."""

    success_url = reverse_lazy('password_change_done')

    def form_valid(self, form):
        response = super().form_valid(form)
        try:
            profile = self.request.user.profile
            if profile.must_change_password:
                profile.must_change_password = False
                profile.save(update_fields=['must_change_password'])
        except Exception:
            # never block the password change on a profile-update glitch
            pass
        return response

from apps.history.audit import log_event, Actions
from apps.history.models import AuditLog

from .decorators import role_required, RoleRequiredMixin
from .models import UserProfile

log = logging.getLogger(__name__)


def _email_temp_password(*, to_email: str, username: str, password: str, kind: str = "created") -> bool:
    """send the new-user / reset-password email. returns True on success.
    failures are logged but never raised — the create/reset view should not
    fail just because email is misconfigured. in dev the console backend
    prints the message instead of sending it."""
    if not to_email:
        return False
    if kind == "reset":
        subject = "[CJPCA] Your password has been reset"
        body = (
            f"Hello {username},\n\n"
            "Your administrator has reset your password.\n\n"
            f"  Username:           {username}\n"
            f"  Temporary password: {password}\n\n"
            "Please log in and change this password immediately. The system "
            "will require you to set a new password before you can access "
            "any other page.\n\n"
            "If you did not request this, contact your administrator.\n"
        )
    else:
        subject = "[CJPCA] Your account is ready"
        body = (
            f"Hello {username},\n\n"
            "An account has been created for you on the Cross-Jurisdictional "
            "Privacy Compliance Analyzer.\n\n"
            f"  Username:           {username}\n"
            f"  Temporary password: {password}\n\n"
            "On first login the system will require you to set a new "
            "password and (if mandated by your administrator) enrol a "
            "TOTP authenticator app for multi-factor authentication.\n\n"
            "If you did not expect this, contact your administrator.\n"
        )
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [to_email],
            fail_silently=False,
        )
        return True
    except Exception as exc:
        log.warning("temp-password email to %s failed: %s", to_email, exc)
        return False


User = get_user_model()


def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _user_has_mfa(user) -> bool:
    """True iff the user has at least one confirmed TOTP device.

    Tolerant of django_otp not being installed yet (Part B). If the package
    is missing the answer is always False.
    """
    try:
        from django_otp import devices_for_user
        return any(devices_for_user(user, confirmed=True))
    except Exception:
        return False


class UserManagementView(RoleRequiredMixin, View):
    allowed_roles = ('admin',)
    template_name = 'accounts/user_management.html'

    def get(self, request):
        q          = request.GET.get('q', '').strip()
        role       = request.GET.get('role', '').strip()
        status     = request.GET.get('status', '').strip()

        users = User.objects.select_related('profile').order_by('username')
        if q:
            users = users.filter(
                Q(username__icontains=q) | Q(email__icontains=q)
                | Q(first_name__icontains=q) | Q(last_name__icontains=q)
            )
        if role in (UserProfile.ANALYST, UserProfile.REVIEWER, UserProfile.ADMIN):
            users = users.filter(profile__role=role)
        if status == 'active':
            users = users.filter(is_active=True)
        elif status == 'disabled':
            users = users.filter(is_active=False)

        # Stats over the unfiltered set
        all_users = User.objects.select_related('profile')
        stats = {
            'total':    all_users.count(),
            'active':   all_users.filter(is_active=True).count(),
            'disabled': all_users.filter(is_active=False).count(),
            'by_role': {
                'analyst':  all_users.filter(profile__role=UserProfile.ANALYST).count(),
                'reviewer': all_users.filter(profile__role=UserProfile.REVIEWER).count(),
                'admin':    all_users.filter(profile__role=UserProfile.ADMIN).count(),
            },
        }

        rows = []
        for u in users[:200]:
            rows.append({
                'pk':         u.pk,
                'username':   u.username,
                'email':      u.email,
                'role':       getattr(getattr(u, 'profile', None), 'role', UserProfile.ANALYST),
                'is_active':  u.is_active,
                'last_login': u.last_login,
                'mfa':        _user_has_mfa(u),
            })

        ctx = {
            'rows':         rows,
            'stats':        stats,
            'q':            q,
            'role_filter':  role,
            'status_filter': status,
            'role_choices': UserProfile.ROLE_CHOICES,
        }
        return render(request, self.template_name, ctx)


@role_required('admin')
def create_user(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    username = request.POST.get('username', '').strip()
    email    = request.POST.get('email', '').strip()
    role     = request.POST.get('role', UserProfile.ANALYST)
    password = request.POST.get('password', '').strip() or _generate_temp_password()
    require_mfa = request.POST.get('require_mfa') == 'on'

    if not username:
        messages.error(request, 'Username is required.')
        return HttpResponseRedirect(reverse('user-management'))

    if User.objects.filter(username=username).exists():
        messages.error(request, f'User "{username}" already exists.')
        return HttpResponseRedirect(reverse('user-management'))

    if role not in (UserProfile.ANALYST, UserProfile.REVIEWER, UserProfile.ADMIN):
        role = UserProfile.ANALYST

    user = User.objects.create_user(username=username, email=email, password=password)
    # The post_save signal already created a profile with role=analyst; update it.
    profile = user.profile
    profile.role = role
    profile.require_mfa_setup = require_mfa
    # newly-created users always start with a temp password they must change
    profile.must_change_password = True
    profile.save(update_fields=['role', 'require_mfa_setup', 'must_change_password'])

    emailed = _email_temp_password(
        to_email=email, username=username, password=password, kind="created",
    )

    log_event(
        request.user, Actions.USER_CREATED,
        request=request,
        target_type='auth.User', target_id=user.pk,
        description=f'{request.user.username} created user "{username}" ({role})',
        metadata={
            'created_username': username, 'role': role,
            'require_mfa': require_mfa, 'email_sent': emailed,
        },
    )

    if emailed:
        messages.success(
            request,
            f'User "{username}" created. Temporary password emailed to {email}.',
        )
    else:
        # fallback so the admin still gets the password if email failed
        messages.success(
            request,
            f'User "{username}" created. Temporary password: {password} '
            f'(email delivery failed — share this manually)',
        )
    return HttpResponseRedirect(reverse('user-management'))


@role_required('admin')
def change_role(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    user = get_object_or_404(User, pk=pk)
    new_role = request.POST.get('role', '').strip()
    if new_role not in (UserProfile.ANALYST, UserProfile.REVIEWER, UserProfile.ADMIN):
        return HttpResponseBadRequest('Invalid role')

    profile = user.profile
    old_role = profile.role
    profile.role = new_role
    profile.save(update_fields=['role'])

    # Cycling sessions on privilege change is wired up in Part C.
    try:
        from .session_utils import force_logout_user
        force_logout_user(user)
    except ImportError:
        pass

    log_event(
        request.user, Actions.USER_ROLE_CHANGED,
        request=request,
        target_type='auth.User', target_id=user.pk,
        description=f'{request.user.username} changed role of {user.username}: {old_role} → {new_role}',
        metadata={'target_username': user.username, 'old_role': old_role, 'new_role': new_role},
    )

    messages.success(request, f'Role updated for {user.username}: {new_role}.')
    return HttpResponseRedirect(reverse('user-management'))


@role_required('admin')
def toggle_active(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, 'You cannot disable your own account.')
        return HttpResponseRedirect(reverse('user-management'))

    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])

    if not user.is_active:
        try:
            from .session_utils import force_logout_user
            force_logout_user(user)
        except ImportError:
            pass

    state = 'enabled' if user.is_active else 'disabled'
    log_event(
        request.user, Actions.USER_DISABLED,
        request=request,
        target_type='auth.User', target_id=user.pk,
        description=f'{request.user.username} {state} user {user.username}',
        metadata={'target_username': user.username, 'is_active_now': user.is_active},
    )

    messages.success(request, f'{user.username} {state}.')
    return HttpResponseRedirect(reverse('user-management'))


@role_required('admin')
def reset_password(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    user = get_object_or_404(User, pk=pk)
    new_password = _generate_temp_password()
    user.set_password(new_password)
    user.save(update_fields=['password'])

    # mark for forced password change on next login
    profile = user.profile
    profile.must_change_password = True
    profile.save(update_fields=['must_change_password'])

    try:
        from .session_utils import force_logout_user
        force_logout_user(user)
    except ImportError:
        pass

    emailed = _email_temp_password(
        to_email=user.email, username=user.username,
        password=new_password, kind="reset",
    )

    log_event(
        request.user, Actions.USER_PASSWORD_RESET,
        request=request,
        target_type='auth.User', target_id=user.pk,
        description=f'{request.user.username} reset password for {user.username}',
        metadata={'target_username': user.username, 'email_sent': emailed},
    )

    if emailed:
        messages.success(
            request,
            f'Password for {user.username} reset. Temporary password emailed to {user.email}.',
        )
    else:
        messages.success(
            request,
            f'Password for {user.username} reset. Temporary password: {new_password} '
            f'(email delivery failed — share this manually)',
        )
    return HttpResponseRedirect(reverse('user-management'))


@require_GET
@login_required
def heartbeat(request):
    """Reset the idle-session timer. The "Stay signed in" button on the
    idle-warning modal hits this endpoint via fetch(). The actual reset
    is done by IdleSessionTimeoutMiddleware before this view runs."""
    return JsonResponse({'ok': True})


@role_required('admin')
def reset_mfa(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')

    user = get_object_or_404(User, pk=pk)
    cleared = 0
    try:
        from django_otp.plugins.otp_totp.models import TOTPDevice
        from django_otp.plugins.otp_static.models import StaticDevice
        cleared += TOTPDevice.objects.filter(user=user).delete()[0]
        cleared += StaticDevice.objects.filter(user=user).delete()[0]
    except ImportError:
        pass

    profile = user.profile
    profile.require_mfa_setup = True
    profile.save(update_fields=['require_mfa_setup'])

    try:
        from .session_utils import force_logout_user
        force_logout_user(user)
    except ImportError:
        pass

    log_event(
        request.user, Actions.MFA_RESET,
        request=request,
        target_type='auth.User', target_id=user.pk,
        description=f'{request.user.username} reset MFA for {user.username}',
        metadata={'target_username': user.username, 'devices_removed': cleared},
    )

    messages.success(
        request,
        f'MFA reset for {user.username}. They will be required to enrol on next login.'
        + (f' ({cleared} device(s) removed)' if cleared else ''),
    )
    return HttpResponseRedirect(reverse('user-management'))


# ── Self-service profile (all roles) ─────────────────────────────────────────


@method_decorator(login_required, name='dispatch')
class ProfileView(TemplateView):
    """Self-service profile for any authenticated user.

    Five sections rendered by ``accounts/profile.html``:
    1. Header (username/email/role/member-since)
    2. Account (password change form, email read-only)
    3. Security (MFA status, regenerate backup codes, MFA disable for admin)
    4. Sessions (active count; the per-user "sign out other sessions" button
       is deferred — the profile template surfaces it as a TODO badge.)
    5. Recent activity (last 10 ``auth.login`` events for this user)
    """

    template_name = 'accounts/profile.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        u = self.request.user
        # Profile attributes are best-effort: signal-created, but defensive.
        profile = getattr(u, 'profile', None)
        ctx['profile_user']   = u
        ctx['profile']        = profile
        ctx['role']           = profile.role if profile else ''
        ctx['role_label']     = profile.get_role_display() if profile else ''
        ctx['mfa_enrolled']   = self._mfa_enrolled(u)
        ctx['backup_codes_remaining'] = self._backup_codes_remaining(u)
        ctx['recent_logins']  = (
            AuditLog.objects
                    .filter(user=u, event_type=Actions.LOGIN)
                    .order_by('-timestamp')[:10]
        )
        ctx['active_session_count'] = self._count_active_sessions(u)
        ctx['password_form']  = PasswordChangeForm(u)
        return ctx

    @staticmethod
    def _mfa_enrolled(user) -> bool:
        try:
            from django_otp.plugins.otp_totp.models import TOTPDevice
            return TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        except Exception:
            return False

    @staticmethod
    def _backup_codes_remaining(user) -> int:
        try:
            from django_otp.plugins.otp_static.models import StaticToken
            return StaticToken.objects.filter(device__user=user).count()
        except Exception:
            return 0

    @staticmethod
    def _count_active_sessions(user) -> int:
        # O(n) over active sessions — fine at our scale (<100 users at BBK).
        # Mirrors the approach in apps.accounts.session_utils.force_logout_user.
        target_id = str(user.pk)
        count = 0
        for s in Session.objects.iterator():
            try:
                data = s.get_decoded()
            except Exception:
                continue
            if str(data.get('_auth_user_id', '')) == target_id:
                count += 1
        return count


@method_decorator(login_required, name='dispatch')
class ChangePasswordView(View):
    """Self-service password change. POST-only; redirects back to profile.

    Uses Django's ``PasswordChangeForm`` so the existing AUTH_PASSWORD_VALIDATORS
    chain (length, similarity, common, numeric) all run unchanged.
    ``update_session_auth_hash`` keeps the user signed in after the password
    rotates — without it, Django would invalidate the current session.
    """

    def post(self, request):
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            log_event(
                user, Actions.USER_PASSWORD_CHANGED,
                request=request,
                target_type='auth.User', target_id=user.pk,
                description=f'{user.username} changed their password',
            )
            messages.success(request, 'Password changed successfully.')
        else:
            # Surface the first field error verbatim so the user can fix it.
            first_error = next(iter(form.errors.values()))[0] if form.errors else 'Invalid input.'
            messages.error(request, f'Password change failed: {first_error}')
        return redirect('profile')


@method_decorator(login_required, name='dispatch')
class RegenerateBackupCodesView(View):
    """Wipe the user's StaticDevice + 10 codes, mint 10 fresh ones, render once.

    The codes are shown a single time on the response page — they are not
    re-displayed on the profile page itself. Users are expected to copy/print
    them at this moment. Same UX as the upstream two_factor backup_tokens
    view, but driven by an admin-blessed self-service button rather than the
    full enrolment wizard.
    """

    def post(self, request):
        try:
            from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
        except ImportError:
            messages.error(request, 'MFA backup codes are unavailable on this server.')
            return redirect('profile')

        StaticDevice.objects.filter(user=request.user).delete()
        device = StaticDevice.objects.create(user=request.user, name='backup', confirmed=True)
        codes = []
        for _ in range(10):
            token = StaticToken.random_token()
            StaticToken.objects.create(device=device, token=token)
            codes.append(token)

        log_event(
            request.user, Actions.AUTH_BACKUP_CODES_REGENERATED,
            request=request,
            target_type='auth.User', target_id=request.user.pk,
            description=f'{request.user.username} regenerated MFA backup codes',
            metadata={'count': len(codes)},
        )
        return render(request, 'accounts/backup_codes_display.html', {'codes': codes})


# ── System monitoring (admin only) ───────────────────────────────────────────


class SystemMonitoringView(RoleRequiredMixin, View):
    """Admin-only operations dashboard.

    Six panels: Ollama health, ChromaDB stats, BM25 stats, sessions, audit
    log volume, and recent ingestion + reasoning failures. **Every panel
    must degrade gracefully.** The page's purpose is to surface
    infrastructure problems — including its own dependencies failing — so
    each data fetch is wrapped in try/except and the panel renders with
    an "unreachable" / "error" badge instead of crashing the page.
    """

    allowed_roles = ('admin',)
    template_name = 'accounts/system_monitoring.html'
    fragment_name = 'accounts/_system_monitoring_panels.html'

    def get(self, request):
        # Performance drift and retraining triggers share three numbers
        # (recent vs baseline approval/confidence/validation-error). Compute
        # once and pass both ways so the two panels can't disagree.
        perf = self._model_performance_drift()
        bias = self._model_bias_parity()
        anomaly = self._model_anomaly_signals()
        ctx = {
            'ollama':                   self._ollama_health(),
            'chroma':                   self._chroma_stats(),
            'bm25':                     self._bm25_stats(),
            'sessions':                 self._session_stats(),
            'audit_log_volume':         self._audit_log_volume(),
            'recent_ingestion_jobs':    self._recent_ingestion_jobs(),
            'recent_validation_errors': self._recent_validation_errors(),
            'recent_logins':            self._recent_logins(),
            'model_performance':        perf,
            'model_bias':               bias,
            'model_anomaly':            anomaly,
            'retraining_triggers':      self._retraining_triggers(perf, bias, anomaly),
        }
        # HTMX poll re-fetches just the panels block — no need to re-render
        # the whole page chrome (sidebar, badges, idle modal) every 30s.
        template = self.fragment_name if getattr(request, 'htmx', False) else self.template_name
        return render(request, template, ctx)

    # ── Panel data fetchers ──────────────────────────────────────────────

    def _ollama_health(self):
        try:
            import requests
            from config import OLLAMA_URL
            r = requests.get(f'{OLLAMA_URL.rstrip("/")}/api/tags', timeout=3)
            r.raise_for_status()
            data = r.json()
            return {
                'status':           'healthy',
                'url':              OLLAMA_URL,
                'models_installed': [m.get('name', '?') for m in data.get('models', [])],
                'response_ms':      int(r.elapsed.total_seconds() * 1000),
            }
        except Exception as exc:
            return {'status': 'unreachable', 'error': str(exc)[:200]}

    def _chroma_stats(self):
        try:
            from ingestion.indexer import get_collection
            # `get_collection()` actually returns the langchain `Chroma`
            # wrapper, not the raw chromadb collection. The wrapper doesn't
            # expose `.count()` — its underlying `_collection` does. Reach
            # through to the raw collection so the panel works against the
            # current langchain version.
            vs = get_collection()
            raw = getattr(vs, '_collection', None) or vs
            count = raw.count()
            return {'status': 'healthy', 'document_count': count}
        except Exception as exc:
            return {'status': 'error', 'error': str(exc)[:200]}

    def _bm25_stats(self):
        import os
        import sqlite3
        try:
            from retrieval.bm25_store import BM25_DB_PATH
            if not os.path.exists(BM25_DB_PATH):
                return {'status': 'missing', 'error': f'No FTS5 DB at {BM25_DB_PATH}'}
            file_size_mb = os.path.getsize(BM25_DB_PATH) / 1024 / 1024
            with sqlite3.connect(str(BM25_DB_PATH)) as conn:
                row_count = conn.execute('SELECT COUNT(*) FROM bm25_index').fetchone()[0]
            return {
                'status':       'healthy',
                'row_count':    row_count,
                'file_size_mb': round(file_size_mb, 1),
                'path':         str(BM25_DB_PATH),
            }
        except Exception as exc:
            return {'status': 'error', 'error': str(exc)[:200]}

    def _session_stats(self):
        try:
            from django.contrib.sessions.models import Session
            from django.utils import timezone
            active = Session.objects.filter(expire_date__gte=timezone.now()).count()
            return {'status': 'healthy', 'active_count': active}
        except Exception as exc:
            return {'status': 'error', 'error': str(exc)[:200]}

    def _audit_log_volume(self):
        try:
            from datetime import timedelta
            from django.utils import timezone
            from apps.history.models import AuditLog
            now      = timezone.now()
            cut_24h  = now - timedelta(hours=24)
            cut_7d   = now - timedelta(days=7)
            return {
                'status':   'healthy',
                'last_24h': AuditLog.objects.filter(timestamp__gte=cut_24h).count(),
                'last_7d':  AuditLog.objects.filter(timestamp__gte=cut_7d).count(),
                'total':    AuditLog.objects.count(),
            }
        except Exception as exc:
            return {'status': 'error', 'error': str(exc)[:200]}

    def _recent_ingestion_jobs(self):
        try:
            from apps.ingestion.models import IngestionJob
            return list(
                IngestionJob.objects
                            .select_related('document')
                            .order_by('-created_at')[:10]
            )
        except Exception:
            return []

    def _recent_logins(self):
        """Most-recent successful + failed login events with the IP each
        came from. Admin uses this to spot odd geographies (e.g. a BBK
        analyst suddenly signing in from outside BH/KW/IN) without leaving
        the monitoring page. We don't run a geo-IP lookup — surfacing the
        raw IP is enough for the eyeball check during the thesis demo and
        avoids shipping a MaxMind DB."""
        try:
            from datetime import timedelta
            from django.utils import timezone
            from apps.history.models import AuditLog
            cut = timezone.now() - timedelta(days=7)
            rows = list(
                AuditLog.objects
                        .filter(event_type__in=[Actions.LOGIN, Actions.LOGIN_FAILED],
                                timestamp__gte=cut)
                        .select_related('user')
                        .order_by('-timestamp')[:15]
            )
            for r in rows:
                # ip_address is a GenericIPAddressField — convert "::1"
                # (IPv6 loopback) and "127.0.0.1" to a friendlier label so
                # the admin doesn't misread their own dev session as suspect.
                if r.ip_address in ('::1', '127.0.0.1', None, ''):
                    r.ip_label = 'localhost'
                else:
                    r.ip_label = r.ip_address
                r.is_failed = (r.event_type == Actions.LOGIN_FAILED)
                # Failed logins have user=NULL — pull the attempted
                # username out of metadata so the row isn't a useless dash.
                if r.user_id and r.user:
                    r.who_label = r.user.username
                else:
                    attempted = ''
                    try:
                        attempted = (r.metadata or {}).get('attempted_username', '')
                    except Exception:
                        pass
                    r.who_label = f'(attempt) {attempted}' if attempted else '—'
            return rows
        except Exception:
            return []

    def _recent_validation_errors(self):
        # Pulled from the AuditLog rows emitted by reasoning/_invoke_with_audit
        # when OutputFixingParser exhausts its retries. Empty in normal
        # operation — Phase 1 of the RAG migration showed zero failures.
        try:
            from datetime import timedelta
            from django.utils import timezone
            from apps.history.models import AuditLog
            cut_24h = timezone.now() - timedelta(hours=24)
            return list(
                AuditLog.objects
                        .filter(event_type=Actions.REASONING_VALIDATION_ERROR,
                                timestamp__gte=cut_24h)
                        .order_by('-timestamp')[:20]
            )
        except Exception:
            return []

    # Model-behaviour panels. Distinct from infra health above: these look
    # at the AI/ML output quality, not the servers. The window is fixed at
    # 7d recent vs the 23 days before it, so the baseline always covers the
    # same span the recent window would after another 7 days pass.

    _DRIFT_RECENT_DAYS = 7
    _DRIFT_BASELINE_DAYS = 23
    _BIAS_GAP_THRESHOLD_PCT = 15
    _RETRAIN_APPROVAL_FLOOR_PCT = 60
    _RETRAIN_HALLUCINATION_CEIL = 0.4
    _RETRAIN_VALIDATION_ERR_CEIL_PCT = 5

    def _model_performance_drift(self):
        try:
            from datetime import timedelta
            from django.db.models import Avg
            from django.utils import timezone
            from apps.comparison.models import ComparisonResult
            from apps.history.models import AuditLog

            now = timezone.now()
            recent_cut = now - timedelta(days=self._DRIFT_RECENT_DAYS)
            baseline_cut = recent_cut - timedelta(days=self._DRIFT_BASELINE_DAYS)

            recent_qs = ComparisonResult.objects.filter(created_at__gte=recent_cut)
            baseline_qs = ComparisonResult.objects.filter(
                created_at__gte=baseline_cut, created_at__lt=recent_cut,
            )

            def _metrics(qs):
                n = qs.count()
                if not n:
                    return {'n': 0, 'avg_conf': None, 'approval': None, 'hall': None}
                approved = qs.filter(lifecycle=ComparisonResult.APPROVED).count()
                rejected = qs.filter(lifecycle=ComparisonResult.REJECTED).count()
                reviewed = approved + rejected
                agg = qs.aggregate(avg=Avg('confidence'), hall=Avg('hallucination_risk'))
                return {
                    'n':        n,
                    'avg_conf': round((agg['avg'] or 0) * 100, 1),
                    'approval': (round(approved / reviewed * 100, 1) if reviewed else None),
                    'hall':     round((agg['hall'] or 0), 3),
                }

            recent = _metrics(recent_qs)
            baseline = _metrics(baseline_qs)

            # Validation-error rate per 100 reasoning runs. The denominator
            # is comparison runs in the window; the numerator is parser
            # failures logged by reasoning/_invoke_with_audit.
            from apps.comparison.models import ComparisonRun
            def _err_rate(start, end):
                runs = ComparisonRun.objects.filter(
                    created_at__gte=start, created_at__lt=end,
                ).count()
                errs = AuditLog.objects.filter(
                    event_type=Actions.REASONING_VALIDATION_ERROR,
                    timestamp__gte=start, timestamp__lt=end,
                ).count()
                if not runs:
                    return None
                return round(errs / runs * 100, 1)
            recent['err_rate']   = _err_rate(recent_cut, now)
            baseline['err_rate'] = _err_rate(baseline_cut, recent_cut)

            def _delta(r, b):
                if r is None or b is None:
                    return None
                return round(r - b, 1)

            drifts = {
                'avg_conf': _delta(recent['avg_conf'], baseline['avg_conf']),
                'approval': _delta(recent['approval'], baseline['approval']),
                'hall':     _delta(recent['hall'], baseline['hall']),
                'err_rate': _delta(recent['err_rate'], baseline['err_rate']),
            }
            # Worst-case status: 'critical' if approval dropped > 10pp or
            # hallucination jumped > 0.1; 'drift' if any single metric moved
            # > 5pp / 0.05; 'stable' otherwise.
            status = 'stable'
            if drifts['approval'] is not None and drifts['approval'] <= -10:
                status = 'critical'
            elif drifts['hall'] is not None and drifts['hall'] >= 0.1:
                status = 'critical'
            elif drifts['err_rate'] is not None and drifts['err_rate'] >= 5:
                status = 'critical'
            else:
                for key, threshold in (('approval', -5), ('avg_conf', -5),
                                       ('hall', 0.05), ('err_rate', 2)):
                    v = drifts[key]
                    if v is None:
                        continue
                    if key in ('hall', 'err_rate'):
                        if v >= threshold:
                            status = 'drift'; break
                    else:
                        if v <= threshold:
                            status = 'drift'; break
            return {
                'status':   'healthy' if recent['n'] else 'no_data',
                'drift_status': status,
                'recent':   recent,
                'baseline': baseline,
                'drifts':   drifts,
                'window_recent_days':   self._DRIFT_RECENT_DAYS,
                'window_baseline_days': self._DRIFT_BASELINE_DAYS,
            }
        except Exception as exc:
            return {'status': 'error', 'error': str(exc)[:200]}

    def _model_bias_parity(self):
        # Bias here means: does the model produce systematically different
        # quality on one jurisdiction pair vs another? Same metric (approval
        # rate among reviewed results) computed per pair_key. A gap of more
        # than _BIAS_GAP_THRESHOLD_PCT between the max and min is flagged.
        try:
            from django.db.models import Avg
            from apps.comparison.models import ComparisonResult
            try:
                from apps.comparison.models import PAIR_CONFIGS
                pair_keys = list(PAIR_CONFIGS.keys())
            except Exception:
                pair_keys = ['bh_in', 'bh_kw', 'in_kw']

            pair_labels = {'bh_in': 'BH ↔ IN', 'bh_kw': 'BH ↔ KW', 'in_kw': 'IN ↔ KW'}
            rows = []
            for pk in pair_keys:
                qs = ComparisonResult.objects.filter(run__pair_key=pk)
                n = qs.count()
                if not n:
                    rows.append({
                        'pair': pk, 'label': pair_labels.get(pk, pk),
                        'n': 0, 'approval': None, 'avg_conf': None,
                    })
                    continue
                approved = qs.filter(lifecycle=ComparisonResult.APPROVED).count()
                rejected = qs.filter(lifecycle=ComparisonResult.REJECTED).count()
                reviewed = approved + rejected
                agg = qs.aggregate(avg=Avg('confidence'))
                rows.append({
                    'pair':     pk,
                    'label':    pair_labels.get(pk, pk),
                    'n':        n,
                    'approval': (round(approved / reviewed * 100, 1) if reviewed else None),
                    'avg_conf': round((agg['avg'] or 0) * 100, 1),
                })
            approvals = [r['approval'] for r in rows if r['approval'] is not None]
            confs     = [r['avg_conf'] for r in rows if r['avg_conf'] is not None]
            approval_gap = (max(approvals) - min(approvals)) if len(approvals) >= 2 else None
            conf_gap     = (max(confs)     - min(confs))     if len(confs)     >= 2 else None
            flagged = (
                (approval_gap is not None and approval_gap > self._BIAS_GAP_THRESHOLD_PCT)
                or (conf_gap is not None and conf_gap > self._BIAS_GAP_THRESHOLD_PCT)
            )
            return {
                'status':       'healthy' if rows else 'no_data',
                'rows':         rows,
                'approval_gap': round(approval_gap, 1) if approval_gap is not None else None,
                'conf_gap':     round(conf_gap, 1)     if conf_gap     is not None else None,
                'threshold':    self._BIAS_GAP_THRESHOLD_PCT,
                'flagged':      flagged,
            }
        except Exception as exc:
            return {'status': 'error', 'error': str(exc)[:200]}

    def _model_anomaly_signals(self):
        # Three signals that could indicate a security event or model
        # misbehaviour. None of these proves an attack on its own; they are
        # heuristics that warrant an admin look.
        try:
            from datetime import timedelta
            from django.utils import timezone
            from apps.comparison.models import ComparisonResult
            from apps.history.models import AuditLog

            now = timezone.now()
            cut_1h  = now - timedelta(hours=1)
            cut_24h = now - timedelta(hours=24)
            cut_7d  = now - timedelta(days=7)

            signals = []

            # Distribution skew: in the last hour, are results overwhelmingly
            # one relationship class compared to the 7-day baseline? An
            # adversarial prompt injection or a model regression often shows
            # up as a sudden monoculture.
            recent_qs = ComparisonResult.objects.filter(created_at__gte=cut_1h)
            recent_n = recent_qs.count()
            if recent_n >= 5:
                from collections import Counter
                recent_dist = Counter(recent_qs.values_list('relationship', flat=True))
                top_rel, top_count = recent_dist.most_common(1)[0]
                top_share = top_count / recent_n * 100
                base_qs = ComparisonResult.objects.filter(
                    created_at__gte=cut_7d, created_at__lt=cut_1h,
                )
                base_n = base_qs.count()
                base_share = 0
                if base_n:
                    base_dist = Counter(base_qs.values_list('relationship', flat=True))
                    base_share = base_dist.get(top_rel, 0) / base_n * 100
                if top_share >= 80 and (top_share - base_share) >= 30:
                    signals.append({
                        'kind':     'distribution_skew',
                        'label':    'Distribution skew',
                        'severity': 'high',
                        'detail':   (
                            f"{top_share:.0f}% of last-hour results are "
                            f"'{top_rel}' (baseline {base_share:.0f}%)"
                        ),
                    })

            # Validation-error spike: more parser failures in the last hour
            # than the 7-day hourly average × 5.
            err_1h = AuditLog.objects.filter(
                event_type=Actions.REASONING_VALIDATION_ERROR,
                timestamp__gte=cut_1h,
            ).count()
            err_7d = AuditLog.objects.filter(
                event_type=Actions.REASONING_VALIDATION_ERROR,
                timestamp__gte=cut_7d, timestamp__lt=cut_1h,
            ).count()
            hourly_baseline = err_7d / (7 * 24) if err_7d else 0
            if err_1h >= 3 and (hourly_baseline == 0 or err_1h >= 5 * hourly_baseline):
                signals.append({
                    'kind':     'validation_error_spike',
                    'label':    'Validation error spike',
                    'severity': 'high',
                    'detail':   (
                        f"{err_1h} parser failures in last hour "
                        f"(7d hourly avg: {hourly_baseline:.2f})"
                    ),
                })

            # Failed-login surge: a credential-stuffing or brute-force
            # attempt is the canonical "security attack" signal a privacy
            # tool's admin needs to see.
            login_fail_24h = AuditLog.objects.filter(
                event_type=Actions.LOGIN_FAILED, timestamp__gte=cut_24h,
            ).count()
            if login_fail_24h >= 20:
                signals.append({
                    'kind':     'failed_login_surge',
                    'label':    'Failed-login surge',
                    'severity': 'high' if login_fail_24h >= 50 else 'medium',
                    'detail':   f"{login_fail_24h} failed login attempts in last 24h",
                })

            # Lopsided request volume: one non-admin user driving > 70% of
            # comparison runs in 24h. Could be a runaway script or a
            # compromised account.
            from apps.comparison.models import ComparisonRun
            runs_24h = ComparisonRun.objects.filter(created_at__gte=cut_24h)
            total_runs = runs_24h.count()
            if total_runs >= 10:
                from django.db.models import Count
                top = (
                    runs_24h.values('created_by__username')
                            .annotate(n=Count('id'))
                            .order_by('-n').first()
                )
                if top and top['n'] / total_runs >= 0.7:
                    signals.append({
                        'kind':     'request_volume_anomaly',
                        'label':    'Request-volume anomaly',
                        'severity': 'medium',
                        'detail':   (
                            f"User '{top['created_by__username'] or 'anonymous'}' ran "
                            f"{top['n']}/{total_runs} comparisons in 24h "
                            f"({top['n'] / total_runs * 100:.0f}%)"
                        ),
                    })

            return {
                'status':         'healthy',
                'signals':        signals,
                'login_fail_24h': login_fail_24h,
                'err_1h':         err_1h,
            }
        except Exception as exc:
            return {'status': 'error', 'error': str(exc)[:200]}

    def _retraining_triggers(self, perf, bias, anomaly):
        # Plain rule engine over the three other panels. Surfaces a single
        # actionable banner at the top of the model section: either "model
        # is operating within thresholds" or a numbered list of conditions
        # the admin should hand to the ML team.
        try:
            triggers = []
            if perf.get('status') == 'healthy':
                r = perf['recent']
                if r.get('approval') is not None and r['approval'] < self._RETRAIN_APPROVAL_FLOOR_PCT:
                    triggers.append(
                        f"Reviewer approval rate {r['approval']}% over last "
                        f"{self._DRIFT_RECENT_DAYS}d (floor {self._RETRAIN_APPROVAL_FLOOR_PCT}%)"
                    )
                if r.get('hall') is not None and r['hall'] > self._RETRAIN_HALLUCINATION_CEIL:
                    triggers.append(
                        f"Avg hallucination risk {r['hall']} "
                        f"(ceiling {self._RETRAIN_HALLUCINATION_CEIL})"
                    )
                if r.get('err_rate') is not None and r['err_rate'] > self._RETRAIN_VALIDATION_ERR_CEIL_PCT:
                    triggers.append(
                        f"Validation error rate {r['err_rate']}% "
                        f"(ceiling {self._RETRAIN_VALIDATION_ERR_CEIL_PCT}%)"
                    )
                if perf.get('drift_status') == 'critical':
                    triggers.append("Performance drift flagged as critical vs baseline")
            if bias.get('flagged'):
                if bias.get('approval_gap') is not None:
                    triggers.append(
                        f"Per-jurisdiction approval gap {bias['approval_gap']}pp "
                        f"(threshold {self._BIAS_GAP_THRESHOLD_PCT}pp)"
                    )
                if bias.get('conf_gap') is not None and (
                    bias.get('approval_gap') is None
                    or bias['conf_gap'] > bias['approval_gap']
                ):
                    triggers.append(
                        f"Per-jurisdiction confidence gap {bias['conf_gap']}pp "
                        f"(threshold {self._BIAS_GAP_THRESHOLD_PCT}pp)"
                    )
            high_anomalies = [
                s for s in anomaly.get('signals', []) if s.get('severity') == 'high'
            ]
            for s in high_anomalies:
                triggers.append(f"Anomaly: {s['detail']}")
            return {'status': 'healthy', 'triggers': triggers}
        except Exception as exc:
            return {'status': 'error', 'error': str(exc)[:200], 'triggers': []}
