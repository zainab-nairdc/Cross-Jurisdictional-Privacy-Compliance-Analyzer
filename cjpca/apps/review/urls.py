from django.urls import path
from . import views

urlpatterns = [
    path('',                        views.ReviewQueueView.as_view(),   name='review'),
    path('item/<int:pk>/',          views.ReviewItemDetailView.as_view(), name='review-item'),
    path('export/<str:format>/',    views.ReviewExportView.as_view(),   name='review-export'),
]
