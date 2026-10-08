from django.conf import settings
from django.db import models

from core.constants import (
    BookingStatus,
    FulfillmentStatus,
    NotificationType,
    PaymentMethod,
    PaymentStatus,
    PaymentType,
    ServiceType,
)
from core.utils import make_id


def booking_id() -> str:
    return make_id('bk')


def notification_id() -> str:
    return make_id('nt')


class Booking(models.Model):
    """A reservation or order for any service type (hotel stay, park permit, shop order, ...)."""

    id = models.CharField(primary_key=True, max_length=64, default=booking_id, editable=False)
    reference = models.CharField(max_length=32, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='bookings',
    )

    # What was booked
    service_type = models.CharField(max_length=32, choices=ServiceType.choices, db_index=True)
    service_id = models.CharField(max_length=120, help_text='Listing id, or "<listing>:<facility>"')
    listing_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    service_name = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)
    image = models.CharField(max_length=500, blank=True)

    # When / how many
    check_in = models.DateField()
    check_out = models.DateField()
    time_slot = models.CharField(max_length=16, blank=True)
    guests = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    # Guest contact
    guest_full_name = models.CharField(max_length=150)
    guest_email = models.EmailField(db_index=True)
    guest_phone = models.CharField(max_length=40, blank=True)
    special_requests = models.TextField(blank=True)

    # Payment
    payment_type = models.CharField(max_length=16, choices=PaymentType.choices)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    payment_status = models.CharField(max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_refunded = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deposit_percent = models.PositiveSmallIntegerField(default=30)
    currency = models.CharField(max_length=3, default='USD')
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(max_length=32, blank=True)

    # Lifecycle
    status = models.CharField(
        max_length=20, choices=BookingStatus.choices, default=BookingStatus.PENDING_PAYMENT, db_index=True
    )
    fulfillment = models.CharField(max_length=20, choices=FulfillmentStatus.choices, null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Soft delete: archived bookings are hidden from lists but kept for records.
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )

    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['service_type', 'listing_id', 'check_in'])]

    def __str__(self):
        return f'{self.reference} · {self.service_name}'

    def save(self, *args, **kwargs):
        if self.listing_id is None and self.service_id:
            head = str(self.service_id).split(':', 1)[0]
            self.listing_id = int(head) if head.isdigit() else None
        super().save(*args, **kwargs)


class Notification(models.Model):
    id = models.CharField(primary_key=True, max_length=64, default=notification_id, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications'
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    type = models.CharField(max_length=16, choices=NotificationType.choices, default=NotificationType.SYSTEM)
    booking = models.ForeignKey(
        Booking, null=True, blank=True, on_delete=models.SET_NULL, related_name='notifications'
    )
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} · {self.title}'
