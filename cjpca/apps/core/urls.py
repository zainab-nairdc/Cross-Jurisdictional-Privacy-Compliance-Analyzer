from django.urls import path
from . import views

urlpatterns = [
    # POST /copilot/message/
    path('copilot/message/', views.CopilotMessageView.as_view(), name='copilot-message'),
    # POST /copilot/feedback/ — thumbs up/down on a Copilot answer
    path('copilot/feedback/', views.CopilotFeedbackView.as_view(), name='copilot-feedback'),
    # POST /copilot/clear/
    path('copilot/clear/', views.CopilotClearView.as_view(), name='copilot-clear'),
    # POST /copilot/toggle-drafts/ (legacy — kept for backwards compat)
    path('copilot/toggle-drafts/', views.CopilotToggleDraftsView.as_view(), name='copilot-toggle-drafts'),
    # GET  /copilot/scope/
    path('copilot/scope/', views.ScopeStateView.as_view(), name='copilot-scope'),
    # PATCH /copilot/scope/preferences/
    path('copilot/scope/preferences/', views.ScopePreferencesView.as_view(), name='copilot-scope-preferences'),
    # GET /viewer/<doc_id>/<article_id>/
    path('viewer/<str:doc_id>/<str:article_id>/', views.DocViewerView.as_view(), name='doc-viewer'),
    # GET/POST /settings/ — site-wide display configuration (admin)
    path('settings/', views.SiteSettingsView.as_view(), name='site-settings'),
    # self-signup is intentionally NOT wired. accounts are created by an
    # admin via /accounts/users/new/ and the new user receives a temp
    # password by email. uncomment only if the deployment needs open
    # registration.
    # path('register/', views.RegisterView.as_view(), name='register'),
]
