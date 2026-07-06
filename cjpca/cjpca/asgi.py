import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')

from django.core.asgi import get_asgi_application

# Initialise the Django ASGI application early so the app registry is populated
# before the channels routing module imports app code.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import cjpca.routing

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(
        URLRouter(cjpca.routing.websocket_urlpatterns)
    ),
})
