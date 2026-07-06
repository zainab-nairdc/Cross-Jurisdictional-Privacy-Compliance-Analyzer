from django.urls import path
from . import views

urlpatterns = [
    # Screen 1 — policy picker
    path('',                              views.PolicySelectView.as_view(),       name='mapping'),

    # Screen 2 — setup form
    path('setup/<int:pk>/',              views.MappingSetupView.as_view(),       name='mapping-setup'),
    path('setup/<int:pk>/run/',          views.MappingRunView.as_view(),         name='mapping-run'),

    # Screen 3 — running / progress
    path('<int:pk>/running/',            views.MappingRunningView.as_view(),     name='mapping-running'),
    path('<int:pk>/cancel/',             views.MappingCancelView.as_view(),      name='mapping-cancel'),
    path('<int:pk>/progress/',           views.MappingProgressAPIView.as_view(), name='mapping-progress'),

    # Screen 4 — results workspace
    path('<int:pk>/',                    views.MappingWorkspaceView.as_view(),   name='mapping-workspace'),

    # HTMX partials & actions
    path('evidence/<int:pk>/',           views.EvidencePanelView.as_view(),      name='mapping-evidence'),
    path('obligation/<int:pk>/override/', views.CoverageOverrideView.as_view(),  name='mapping-coverage-override'),
    path('obligation/<int:pk>/severity/', views.ObligationSeverityOverrideView.as_view(), name='mapping-severity-override'),
    path('gap/<int:pk>/save/',           views.GapRemediationSaveView.as_view(), name='mapping-gap-save'),
    path('gap/<int:pk>/suggest/',        views.GapAISuggestView.as_view(),       name='mapping-gap-suggest'),
    path('<int:pk>/send-to-review/',     views.SendToReviewView.as_view(),       name='mapping-send-to-review'),
    path('<int:pk>/validate/',           views.ValidateAnalysisView.as_view(),   name='mapping-validate'),
    path('obligation/<int:pk>/transition/', views.ObligationMappingTransitionView.as_view(), name='mapping-obligation-transition'),

    # Screen 5 — dual-regulation comparison: policy vs reg-A AND reg-B side-by-side
    path('dual/',                        views.DualMappingView.as_view(),      name='mapping-dual'),

    # Action assignment on gaps
    path('gap/<int:pk>/assign/',         views.GapAssignView.as_view(),         name='mapping-gap-assign'),

    # Approved-package exports (executive summary PDF + gap register XLSX)
    path('<int:pk>/exports/exec-summary.pdf',
         views.MappingExecSummaryView.as_view(),
         name='mapping-export-pdf'),
    path('<int:pk>/exports/gap-register.xlsx',
         views.MappingGapRegisterView.as_view(),
         name='mapping-export-xlsx'),
]
