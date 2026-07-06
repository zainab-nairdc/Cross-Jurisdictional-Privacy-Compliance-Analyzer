from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # Page 1 — Home dashboard
    path('', include('apps.home.urls')),

    # Page 2 — Regulation comparison
    path('comparison/', include('apps.comparison.urls')),

    # Page 3 — Policy mapping & gap analysis
    path('mapping/', include('apps.mapping.urls')),

    # Page 4 — Review & validate
    path('review/', include('apps.review.urls')),

    # Page 7 — Analytics dashboard
    path('analytics/', include('apps.analytics.urls')),

    # Page 8 — History & audit log
    path('history/', include('apps.history.urls')),

# Pages 5 & 6 — Document libraries (regulations + policies + upload)
    path('library/', include('apps.library.urls')),

    # Ingestion management (HTMX widget + jobs page)
    path('ingestion/', include('apps.ingestion.urls')),

    # ── /accounts/ namespace ────────────────────────────────────────────────
    # Our own logout override — included first so it wins over the built-in.
    path('accounts/', include('apps.accounts.urls')),

    # Django's built-in auth views: login + logout + password_change/reset.
    path('accounts/', include('django.contrib.auth.urls')),

    # Global overlays: Copilot + Doc viewer + register (mounted at root to keep URLs clean)
    path('', include('apps.core.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
