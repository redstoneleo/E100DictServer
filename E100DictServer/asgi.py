"""
ASGI config for E100DictServer project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""

import os

# Ensure the Django settings module is set before importing any Django apps or
# modules that may import Django models. This prevents AppRegistryNotReady when
# the ASGI module is imported by an ASGI server like uvicorn/daphne.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'E100DictServer.settings')

from django.core.asgi import get_asgi_application

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from ChatBot.middleware import JWTAuthMiddleware
from ChatBot import routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddleware(
        URLRouter(
            routing.websocket_urlpatterns
        )
    ),
})