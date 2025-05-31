# interview_project/asgi.py
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
# from channels.auth import AuthMiddlewareStack # If you add Django auth later
import interview_app.routing # Make sure this import is correct

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'interview_project.settings')

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": URLRouter( # Ensure this uses your routing
            interview_app.routing.websocket_urlpatterns
        )
})