from django.urls import path
from django.views.generic import RedirectView
from . import views
from .api import (
    DocumentStrictnessView, ComparisonArcsView,
    AvailablePairsView, TopicScanView, RunStatusView,
    RunOverviewView, RunClausesView, RunGraphView, RunArcsView,
    RunTopicMapView, RunInsightsView,
    ResultDetailView, ResultTransitionView, ResultNoteView,
)

# Consolidated comparison flow — single landing page, synchronous run, rich
# results UI rehydrated from saved report JSON. The /analyst/, /custom/scope/,
# /setup/, and V1 routes are kept as redirects so external links don't 404.

urlpatterns = [
    path('', views.PairPickerView.as_view(), name='comparison'),
    path('run/', views.RunComparisonView.as_view(), name='comparison-run'),
    path('runs/<int:pk>/', views.ComparisonWorkspaceView.as_view(), name='comparison-workspace'),
    path('runs/<int:pk>/submit-review/', views.SubmitForReviewView.as_view(), name='comparison-submit-review'),

    # ── Back-compat redirects: old routes funnel into the new combined page ──
    # query_string=True preserves ?reg_a_pk=… selections when the picker JS
    # accidentally hits an old URL (e.g. cached page reload after the routes
    # were consolidated).
    # Temporarily kept live (was redirected to /comparison/). User asked
    # for it back so they can side-by-side compare the new combined page
    # against the legacy analyst page. Delete once we're sure outputs match.
    path('analyst/',        views.AnalystComparisonView.as_view(), name='comparison-analyst'),
    path('custom/scope/',   RedirectView.as_view(pattern_name='comparison', permanent=False, query_string=True), name='comparison-custom-scope'),
    path('setup/',          RedirectView.as_view(pattern_name='comparison', permanent=False, query_string=True), name='comparison-setup'),
    # Static url= (not pattern_name) — RedirectView would otherwise forward the
    # captured `pair_key` into reverse('comparison'), which takes no args, and
    # 500 with NoReverseMatch. Matches the v1/ redirects below.
    path('<str:pair_key>/scope/', RedirectView.as_view(url='/comparison/', permanent=False, query_string=True), name='comparison-scope'),
    path('runs/<int:pk>/progress/', views.ComparisonWorkspaceView.as_view(), name='comparison-progress'),

    # ── API ─────────────────────────────────────────────────────────────────
    path('api/pairs/',      AvailablePairsView.as_view(), name='comparison-pairs'),
    path('api/topic-scan/', TopicScanView.as_view(), name='comparison-topic-scan'),
    path('api/documents/<int:pk>/strictness/', DocumentStrictnessView.as_view(), name='document-strictness'),

    path('runs/<int:pk>/status/',     RunStatusView.as_view(), name='comparison-run-status'),
    path('runs/<int:pk>/overview/',   RunOverviewView.as_view(), name='comparison-run-overview'),
    path('runs/<int:pk>/clauses/',    RunClausesView.as_view(), name='comparison-run-clauses'),
    path('runs/<int:pk>/graph/',      RunGraphView.as_view(), name='comparison-run-graph'),
    path('runs/<int:pk>/arcs/',       RunArcsView.as_view(), name='comparison-run-arcs'),
    path('runs/<int:pk>/topic-map/',  RunTopicMapView.as_view(), name='comparison-run-topic-map'),
    path('runs/<int:pk>/insights/',   RunInsightsView.as_view(), name='comparison-run-insights'),

    path('results/<int:pk>/detail/',     ResultDetailView.as_view(),     name='comparison-result-detail'),
    path('results/<int:pk>/transition/', ResultTransitionView.as_view(), name='comparison-result-transition'),
    path('results/<int:pk>/note/',       ResultNoteView.as_view(),       name='comparison-result-note'),

    # V1 endpoints kept only because templates and audit logs still reference
    # the URL names — they 302 to /comparison/ now. Use a static `url=` so
    # RedirectView doesn't try to feed the captured `pk` kwarg into
    # `reverse('comparison')`, which takes no args (would NoReverseMatch → 500).
    path('v1/<int:pk>/',             RedirectView.as_view(url='/comparison/', permanent=False), name='comparison-workspace-v1'),
    path('v1/pair/<int:pk>/',        RedirectView.as_view(url='/comparison/', permanent=False), name='comparison-pair'),
    path('v1/<int:pk>/graph-data/',  RedirectView.as_view(url='/comparison/', permanent=False), name='comparison-graph-data'),
    path('api/comparisons/<int:pk>/arcs/', ComparisonArcsView.as_view(), name='comparison-arcs'),

    # Approved-package exports (executive summary PDF + comparison register XLSX)
    path('runs/<int:pk>/exports/exec-summary.pdf',
         views.ComparisonExecSummaryView.as_view(),
         name='comparison-export-pdf'),
    path('runs/<int:pk>/exports/comparison-register.xlsx',
         views.ComparisonRegisterView.as_view(),
         name='comparison-export-xlsx'),
]
