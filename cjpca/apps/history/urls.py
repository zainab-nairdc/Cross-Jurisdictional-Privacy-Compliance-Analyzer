from django.urls import path
from . import views

urlpatterns = [
    path('',           views.HistoryView.as_view(),      name='history'),
    path('<slug:pk>/', views.EventDetailView.as_view(),  name='history-event'),
]
