from django.urls import re_path
from apps.ingestion import consumers

# WebSocket URL patterns — consumed by ProtocolTypeRouter in asgi.py
websocket_urlpatterns = [
    # WS /ws/ingestion/<job_id>/  — live ingestion log stream
    re_path(r'^ws/ingestion/(?P<job_id>[^/]+)/$', consumers.IngestionConsumer.as_asgi()),
]
