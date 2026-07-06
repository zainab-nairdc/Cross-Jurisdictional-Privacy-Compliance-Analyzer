from django.urls import path
from . import views

urlpatterns = [
    path('',               views.AnalyticsView.as_view(),       name='analytics'),
    path('data/',          views.AnalyticsDataView.as_view(),   name='analytics-data'),
    path('heatmap/',       views.HeatmapPartialView.as_view(),  name='analytics-heatmap'),
    path('heatmap/data/',  views.HeatmapDataView.as_view(),     name='analytics-heatmap-data'),
    path('gaps/',          views.GapRegisterView.as_view(),     name='analytics-gaps'),
    path('cross-gap/',     views.CrossJurisdictionGapView.as_view(), name='analytics-cross-gap'),
    path('conflicts/',     views.ConflictScannerView.as_view(),      name='analytics-conflicts'),
]
