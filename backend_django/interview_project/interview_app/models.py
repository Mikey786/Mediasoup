# interview_app/models.py
import uuid
from django.db import models
from django.conf import settings # If you store user model

class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    # Assuming host_client_id is a temporary identifier for the WebSocket session
    # For a more robust system, you'd link to a Django User model if you have auth
    host_client_id = models.CharField(max_length=255, null=True, blank=True)
    # host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="hosted_rooms") # Alternative if using Django users
    created_at = models.DateTimeField(auto_now_add=True)
    router_rtp_capabilities = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.name

class Participant(models.Model):
    room = models.ForeignKey(Room, related_name='participants', on_delete=models.CASCADE)
    client_id = models.CharField(max_length=255, unique=True) # WebSocket client_id
    display_name = models.CharField(max_length=100)
    is_host = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.display_name} ({'Host' if self.is_host else 'Attendee'}) in {self.room.name}"