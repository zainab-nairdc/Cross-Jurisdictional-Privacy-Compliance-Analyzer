from django.urls import path
from . import views

urlpatterns = [
    path('regulations/',           views.RegulationsView.as_view(),    name='library-regulations'),
    path('policies/',              views.PoliciesView.as_view(),       name='library-policies'),
    # PoC scope: Term Dictionary, Cross-reference search and Obligation
    # register removed — not part of the Step 1–4 feature spec.
    path('upload/',                views.DocumentUploadView.as_view(), name='library-upload'),
    path('upload/preview/',        views.UploadMetadataPreviewView.as_view(), name='library-upload-preview'),
    path('delete/<int:pk>/',       views.DocumentDeleteView.as_view(), name='library-delete'),
    path('view/<int:pk>/',         views.DocumentViewerView.as_view(), name='library-view'),
    path('<int:pk>/tags/',         views.DocumentTagView.as_view(),    name='library-tags'),
]
