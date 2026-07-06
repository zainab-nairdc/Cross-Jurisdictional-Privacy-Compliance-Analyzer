from pathlib import Path
import os
import sys

BASE_DIR = Path(__file__).resolve().parent.parent

# Make the repo root importable so ingestion/retrieval/reasoning modules resolve
sys.path.insert(0, str(BASE_DIR.parent))

# Load .env from project root if present
_env_file = BASE_DIR.parent / '.env'
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SECRET_KEY = 'django-insecure-cjpca-replace-in-production'

# DEBUG controls dev-friendly error pages + a cluster of production-aware
# switches further down (HSTS, secure cookies, SSL redirect). Default True
# for local dev. Set DEBUG=False in .env (or the deploy environment) to
# activate production hardening.
DEBUG = os.environ.get('DEBUG', 'true').lower() not in ('0', 'false', 'no', 'off')

# 'testserver' is the host the Django test client uses; without it every
# self-test 400s with DisallowedHost. Safe to keep in dev (DEBUG=True);
# in production set DJANGO_ALLOWED_HOSTS to a comma-separated list of the
# real hostnames you deploy under.
_default_hosts = 'localhost,127.0.0.1,testserver'
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', _default_hosts).split(',')
    if h.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third-party
    'channels',
    'django_htmx',
    'widget_tweaks',
    # project apps
    'apps.core.apps.CoreConfig',
    'apps.home.apps.HomeConfig',
    'apps.comparison.apps.ComparisonConfig',
    'apps.mapping.apps.MappingConfig',
    'apps.review.apps.ReviewConfig',
    'apps.analytics.apps.AnalyticsConfig',
    'apps.history.apps.HistoryConfig',
    'apps.library.apps.LibraryConfig',
    'apps.ingestion.apps.IngestionConfig',
    'apps.accounts.apps.AccountsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
]

ROOT_URLCONF = 'cjpca.urls'
ASGI_APPLICATION = 'cjpca.asgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # injects nav badge counts into every template context
                'apps.core.context_processors.nav_counts',
                # injects user_role / is_analyst / is_reviewer / is_admin
                'apps.accounts.context_processors.user_role',
            ],
        },
    },
]

WSGI_APPLICATION = 'cjpca.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ---------------------------------------------------------------------------
# Django Channels
# In-memory channel layer for development.
# For production swap to Redis:
#   BACKEND: 'channels_redis.core.RedisChannelLayer'
#   CONFIG:  {'hosts': [('127.0.0.1', 6379)]}
# ---------------------------------------------------------------------------
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    # PoC: Django's default validators only.
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# Tailwind is compiled via the standalone Tailwind CLI:
#   npx tailwindcss -i static/css/tailwind.css -o static/css/output.css --watch
# Reference static/css/output.css in base.html, not tailwind.css.
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files (user-uploaded regulation/policy documents)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication — plain Django username/password login (no roles, no MFA).
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]


# Security headers
# every header below is a defence against a specific attack class. defaults
# are tuned for the BBK deployment; flip via env vars if they break dev.
#
#   HSTS                          — forces https for 1 year
#   X-Content-Type-Options        — prevents mime-confusion attacks
#   X-Frame-Options               — prevents clickjacking
#   Referrer-Policy               — strips full url from cross-origin referer
#   secure cookies                — session + csrf cookies marked Secure + HttpOnly
#   SECURE_SSL_REDIRECT           — http -> https in prod (off in dev)
SECURE_HSTS_SECONDS              = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000' if not DEBUG else '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS   = not DEBUG
SECURE_HSTS_PRELOAD              = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF      = True
SECURE_REFERRER_POLICY           = 'same-origin'
SECURE_BROWSER_XSS_FILTER        = True   # legacy, harmless to set
SECURE_SSL_REDIRECT              = not DEBUG
X_FRAME_OPTIONS                  = 'DENY'
SESSION_COOKIE_SECURE            = not DEBUG
SESSION_COOKIE_HTTPONLY          = True
SESSION_COOKIE_SAMESITE          = 'Lax'
CSRF_COOKIE_SECURE               = not DEBUG
# CSRF cookie must be readable from JS — the in-page tag editor and other
# Alpine/HTMX components send the X-CSRFToken header by reading the cookie
# via document.cookie. HttpOnly=True would silently break those POSTs (the
# JS reads an empty string and Django rejects with "incorrect length").
# We still get XSS protection via CSP's restricted script-src and the fact
# that the token is single-use per session.
CSRF_COOKIE_HTTPONLY             = False
CSRF_COOKIE_SAMESITE             = 'Lax'

# Email configuration
# the admin-creates-user flow emails the new user their temp password.
# default backend prints to the console — fine for dev / demo, swap to SMTP
# (or anymail / sendgrid) in production by overriding via env vars.
EMAIL_BACKEND      = os.environ.get('EMAIL_BACKEND',      'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST         = os.environ.get('EMAIL_HOST',         'localhost')
EMAIL_PORT         = int(os.environ.get('EMAIL_PORT',     '25'))
EMAIL_HOST_USER    = os.environ.get('EMAIL_HOST_USER',    '')
EMAIL_HOST_PASSWORD= os.environ.get('EMAIL_HOST_PASSWORD','')
EMAIL_USE_TLS      = os.environ.get('EMAIL_USE_TLS', 'false').lower() in ('1','true','yes','on')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@cjpca.local')

# ── Session ──────────────────────────────────────────────────────────────────
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# ── Production hardening (gated on DEBUG) ────────────────────────────────────
# These break localhost over plain HTTP, so they only fire when DEBUG=False.
if not DEBUG:
    SESSION_COOKIE_SECURE = True   # session cookie only sent over HTTPS
    CSRF_COOKIE_SECURE    = True   # CSRF cookie too
    SECURE_SSL_REDIRECT   = True   # auto-redirect HTTP → HTTPS
    SECURE_HSTS_SECONDS   = 31536000   # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD            = True
    SECURE_BROWSER_XSS_FILTER      = True
    SECURE_CONTENT_TYPE_NOSNIFF    = True
    X_FRAME_OPTIONS                = 'DENY'
