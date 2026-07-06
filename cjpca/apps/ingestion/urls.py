from django.urls import path
from . import views

urlpatterns = [
    # GET /ingestion/widget/   — HTMX polling fragment (home page widget)
    path('widget/', views.IngestionWidgetView.as_view(), name='ingestion-widget'),
    # GET  /ingestion/quarantine/                — quarantine queue
    # POST /ingestion/quarantine/<pk>/<action>/  — approve/reject a flagged chunk
    path('quarantine/',                   views.QuarantineQueueView.as_view(),  name='quarantine-queue'),
    path('quarantine/<int:pk>/<str:action>/', views.QuarantineDecideView.as_view(), name='quarantine-decide'),
]
