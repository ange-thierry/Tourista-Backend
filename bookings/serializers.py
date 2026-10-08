from datetime import date

from rest_framework import serializers

from core.constants import (
    BookingStatus,
    FulfillmentStatus,
    PaymentMethod,
    PaymentType,
    ServiceType,
)
from core.utils import iso, money

from .models import Booking, Notification


def booking_to_frontend(b: Booking) -> dict:
    """Serialize to the frontend `Booking` interface (camelCase, nested guestInfo/payment)."""
    guest_info = {'fullName': b.guest_full_name, 'email': b.guest_email, 'phone': b.guest_phone}
    if b.special_requests:
        guest_info['specialRequests'] = b.special_requests

    data = {
        'id': b.id,
        'reference': b.reference,
        'userId': str(b.user_id) if b.user_id else None,
        'serviceType': b.service_type,
        'serviceId': int(b.service_id) if b.service_id.isdigit() else b.service_id,
        'serviceName': b.service_name,
        'location': b.location,
        'image': b.image or None,
        'checkIn': b.check_in.isoformat(),
        'checkOut': b.check_out.isoformat(),
        'timeSlot': b.time_slot or None,
        'guests': b.guests,
        'unitPrice': money(b.unit_price),
        'guestInfo': guest_info,
        'payment': {
            'type': b.payment_type,
            'method': b.payment_method,
            'status': b.payment_status,
            'totalAmount': money(b.total_amount),
            'amountPaid': money(b.amount_paid),
            'amountDue': money(b.amount_due),
            'amountRefunded': money(b.amount_refunded),
            'depositPercent': b.deposit_percent,
            'currency': b.currency,
            'paidAt': iso(b.paid_at),
            'reference': b.payment_reference,
        },
        'status': b.status,
        'fulfillment': b.fulfillment,
        'createdAt': iso(b.created_at),
        'updatedAt': iso(b.updated_at),
        'checkedInAt': iso(b.checked_in_at),
        'checkedOutAt': iso(b.checked_out_at),
        'notes': b.notes or None,
        'listingId': b.listing_id,
        'isArchived': b.is_archived or None,
        'archivedAt': iso(b.archived_at),
    }
    # Omit nulls so optional TS fields are `undefined`, as before.
    return {key: value for key, value in data.items() if value is not None}


def booking_to_occupancy(b: Booking) -> dict:
    """Public, PII-free view used by availability calendars."""
    return {
        'id': b.id,
        'serviceType': b.service_type,
        'serviceId': int(b.service_id) if b.service_id.isdigit() else b.service_id,
        'serviceName': b.service_name,
        'checkIn': b.check_in.isoformat(),
        'checkOut': b.check_out.isoformat(),
        **({'timeSlot': b.time_slot} if b.time_slot else {}),
        'guests': b.guests,
        'status': b.status,
    }


class FlexibleDateField(serializers.DateField):
    """Accepts `YYYY-MM-DD` as well as full ISO datetimes (keeps the date part)."""

    def to_internal_value(self, value):
        if isinstance(value, str) and len(value) > 10 and value[4] == '-':
            value = value[:10]
        return super().to_internal_value(value)


class GuestInfoSerializer(serializers.Serializer):
    fullName = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=40, allow_blank=True, required=False, default='')
    specialRequests = serializers.CharField(allow_blank=True, required=False, default='')


class QuoteSerializer(serializers.Serializer):
    """What is being booked and when. Prices are always computed by the server."""

    serviceType = serializers.ChoiceField(choices=ServiceType.choices)
    serviceId = serializers.CharField(max_length=120)
    checkIn = FlexibleDateField()
    checkOut = FlexibleDateField(required=False, allow_null=True)
    timeSlot = serializers.CharField(max_length=32, allow_blank=True, required=False, allow_null=True)
    guests = serializers.IntegerField(min_value=1, max_value=500, default=1)

    def validate(self, attrs):
        if not attrs.get('checkOut'):
            attrs['checkOut'] = attrs['checkIn']
        if attrs['checkOut'] < attrs['checkIn']:
            raise serializers.ValidationError({'checkOut': 'Check-out cannot be before check-in.'})
        return attrs

    def to_service_input(self) -> dict:
        v = self.validated_data
        return {
            'service_type': v['serviceType'],
            'service_id': v['serviceId'],
            'check_in': v['checkIn'],
            'check_out': v['checkOut'],
            'time_slot': (v.get('timeSlot') or '').strip(),
            'guests': v['guests'],
        }


class CreateBookingSerializer(QuoteSerializer):
    """Accepts the frontend `CreateBookingInput` payload.

    `unitPrice`, `totalAmount`, `serviceName`, `location`, `image` and `depositPercent`
    are accepted for backwards compatibility but ignored: the server prices the booking.
    """

    guestInfo = GuestInfoSerializer()
    paymentType = serializers.ChoiceField(choices=PaymentType.choices)
    paymentMethod = serializers.ChoiceField(choices=PaymentMethod.choices)

    def to_service_input(self) -> dict:
        data = super().to_service_input()
        v = self.validated_data
        guest = v['guestInfo']
        data.update({
            'guest_full_name': guest['fullName'].strip(),
            'guest_email': guest['email'].strip(),
            'guest_phone': guest.get('phone', '').strip(),
            'special_requests': guest.get('specialRequests', '').strip(),
            'payment_type': v['paymentType'],
            'payment_method': v['paymentMethod'],
        })
        return data


class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=BookingStatus.choices)


class PayBalanceSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False)


class FulfillmentSerializer(serializers.Serializer):
    fulfillment = serializers.ChoiceField(choices=FulfillmentStatus.choices)


def notification_to_frontend(n: Notification) -> dict:
    data = {
        'id': n.id,
        'userId': str(n.user_id),
        'title': n.title,
        'message': n.message,
        'type': n.type,
        'read': n.read,
        'createdAt': iso(n.created_at),
    }
    if n.booking_id:
        data['bookingId'] = n.booking_id
    return data
