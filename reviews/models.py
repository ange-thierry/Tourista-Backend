from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.constants import ServiceType


class Review(models.Model):
    """A guest review, only possible after a completed stay/visit/order (one per booking)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    booking = models.OneToOneField('bookings.Booking', on_delete=models.CASCADE, related_name='review')
    service_type = models.CharField(max_length=32, choices=ServiceType.choices, db_index=True)
    listing_id = models.PositiveIntegerField(db_index=True)
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120, blank=True)
    comment = models.TextField(max_length=3000)
    reply = models.TextField(blank=True, max_length=3000)
    replied_at = models.DateTimeField(null=True, blank=True)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['service_type', 'listing_id', 'is_published'])]

    def __str__(self):
        return f'{self.rating}★ {self.service_type} {self.listing_id} by {self.user}'
