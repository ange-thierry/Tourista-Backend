from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """A thread between a guest and the provider that manages a listing,
    optionally about a specific booking."""

    guest = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations')
    workspace = models.ForeignKey(
        'providers.ProviderWorkspace', on_delete=models.CASCADE, related_name='conversations'
    )
    booking = models.ForeignKey(
        'bookings.Booking', null=True, blank=True, on_delete=models.SET_NULL, related_name='conversations'
    )
    subject = models.CharField(max_length=200)
    guest_last_read_at = models.DateTimeField(null=True, blank=True)
    provider_last_read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.subject} ({self.guest} ↔ {self.workspace})'


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    body = models.TextField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
