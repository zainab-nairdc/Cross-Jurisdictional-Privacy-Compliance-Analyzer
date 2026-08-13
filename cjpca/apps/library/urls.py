from django.urls import path
from . import review_views, views

urlpatterns = [
    # ── Phase 3: requirement review + human-governed taxonomy expansion ──
    path('requirements/',                review_views.RequirementListView.as_view(),
         name='library-requirements'),
    path('requirements/<int:pk>/',       review_views.RequirementDetailView.as_view(),
         name='library-requirement-detail'),
    path('requirements/<int:pk>/topics/',
         review_views.RequirementTopicActionView.as_view(),
         name='library-requirement-topics'),
    path('topic-suggestions/',           review_views.TopicSuggestionQueueView.as_view(),
         name='library-topic-suggestions'),
    path('topic-suggestions/new/',       review_views.TopicSuggestionCreateView.as_view(),
         name='library-topic-suggestion-create'),
    path('topic-suggestions/<int:pk>/',  review_views.TopicSuggestionDetailView.as_view(),
         name='library-topic-suggestion-detail'),
    path('topic-suggestions/<int:pk>/action/',
         review_views.TopicSuggestionActionView.as_view(),
         name='library-topic-suggestion-action'),

    path('regulations/',           views.RegulationsView.as_view(),    name='library-regulations'),
    path('policies/',              views.PoliciesView.as_view(),       name='library-policies'),
    # PoC scope: Term Dictionary, Cross-reference search and Obligation
    # register removed — not part of the Step 1–4 feature spec.
    path('add/',                   views.AddDocumentView.as_view(),    name='library-add'),
    path('upload/',                views.DocumentUploadView.as_view(), name='library-upload'),
    path('upload/preview/',        views.UploadMetadataPreviewView.as_view(), name='library-upload-preview'),
    path('analyze/',               views.AnalyzeView.as_view(),   name='library-analyze'),
    path('finalize/<int:pk>/',     views.FinalizeView.as_view(),  name='library-finalize'),
    path('delete/<int:pk>/',       views.DocumentDeleteView.as_view(), name='library-delete'),
    path('<int:pk>/supersede/',    views.DocumentSupersedeView.as_view(), name='library-supersede'),
    path('view/<int:pk>/',         views.DocumentViewerView.as_view(), name='library-view'),
    path('structure/<int:pk>/',    views.DocumentStructureView.as_view(), name='library-structure'),
    path('<int:pk>/tags/',         views.DocumentTagView.as_view(),    name='library-tags'),
]
