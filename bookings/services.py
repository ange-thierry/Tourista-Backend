"""Booking lifecycle: creation, status/fulfillment transitions, payments, archiving."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.constants import (
    BookingStatus,
    FulfillmentStatus,
    NotificationType,
    PaymentStatus,
    PaymentType,
    ServiceType,
)
from core.emails import send_booking_email, send_provider_booking_email
from core.utils import make_reference
from listings.models import Listing

from . import engine
from .models import Booking, Notification

User = get_user_model()

ZERO = Decimal('0')

# Service types that track a fulfillment step besides the booking status.
FULFILLMENT_SERVICE_TYPES = {ServiceType.SHOP, ServiceType.SPA, ServiceType.RESTAURANT, ServiceType.ARTISAN}

# Which status may follow which. Anything else is rejected.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    BookingStatus.PENDING_PAYMENT: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CHECKED_IN, BookingStatus.CANCELLED, BookingStatus.COMPLETED},
    BookingStatus.CHECKED_IN: {BookingStatus.CHECKED_OUT, BookingStatus.COMPLETED},
    BookingStatus.CHECKED_OUT: {BookingStatus.COMPLETED},
    BookingStatus.CANCELLED: set(),
    BookingStatus.COMPLETED: set(),
}

# Ordered fulfillment steps; a booking can only move forward along its track.
FULFILLMENT_TRACKS = {
    ServiceType.SHOP: [
        FulfillmentStatus.NOT_STARTED,
        FulfillmentStatus.PREPARING,
        FulfillmentStatus.READY,
        FulfillmentStatus.OUT_FOR_DELIVERY,
        FulfillmentStatus.DELIVERED,
    ],
    'service': [FulfillmentStatus.NOT_STARTED, FulfillmentStatus.IN_SERVICE, FulfillmentStatus.FULFILLED],
}
FINAL_FULFILLMENT = {FulfillmentStatus.DELIVERED, FulfillmentStatus.FULFILLED}
ACTIVE_FULFILLMENT = {FulfillmentStatus.OUT_FOR_DELIVERY, FulfillmentStatus.IN_SERVICE}


def _unique_reference() -> str:
    while True:
        ref = make_reference()
        if not Booking.objects.filter(reference=ref).exists():
            return ref


def _fmt(amount: Decimal) -> str:
    """Format like JS `${n}`: 540 not 540.00, 37.5 not 37.50."""
    return f'{Decimal(amount).normalize():f}'


def booking_providers(booking: Booking):
    """Provider accounts that manage this booking's listing."""
    from providers.models import ProviderWorkspace

    return [
        ws.user
        for ws in ProviderWorkspace.objects.filter(
            service_type=booking.service_type, linked_listing_id=booking.listing_id, user__is_active=True
        ).select_related('user')
    ]


def notify(user, *, title: str, message: str, type: str, booking: Booking | None = None):
    if user is None:
        return None
    return Notification.objects.create(user=user, title=title, message=message, type=type, booking=booking)


def _settle(booking: Booking, now) -> None:
    """Record any outstanding balance as collected by the provider."""
    if booking.amount_due > 0:
        booking.amount_paid = booking.total_amount
        booking.amount_due = ZERO
        booking.payment_status = PaymentStatus.PAID
        booking.paid_at = now


def _take_stock(spec: engine.ServiceSpec, quantity: int) -> None:
    holder = spec.stock_holder
    if holder is None:
        return
    taken = type(holder).objects.filter(pk=holder.pk, stock__gte=quantity).update(stock=F('stock') - quantity)
    if not taken:
        raise ValidationError({'guests': 'Not enough stock left for this order.'})


def _return_stock(spec: engine.ServiceSpec, quantity: int) -> None:
    holder = spec.stock_holder
    if holder is not None:
        type(holder).objects.filter(pk=holder.pk).update(stock=F('stock') + quantity)


def quote(data: dict) -> dict:
    """Price + availability for a prospective booking (no side effects)."""
    spec = engine.resolve(data['service_type'], data['service_id'])
    check_in, check_out = engine.normalize_dates(spec, data['check_in'], data['check_out'])
    result = {
        'serviceName': spec.name,
        'location': spec.location,
        'image': spec.image,
        'schedule': spec.schedule,
        'maxGuests': spec.max_guests,
        'stock': spec.stock,
        **engine.price_for(spec, check_in, check_out, data['guests']),
        'available': True,
        'reason': None,
    }
    try:
        engine.check_availability(spec, check_in, check_out, data.get('time_slot'), data['guests'])
    except ValidationError as exc:
        result['available'] = False
        detail = exc.detail
        if isinstance(detail, dict):
            detail = next(iter(detail.values()))
        result['reason'] = str(detail[0] if isinstance(detail, list) else detail)
    return result


@transaction.atomic
def create_booking(data: dict, user=None) -> Booking:
    spec = engine.resolve(data['service_type'], data['service_id'])
    # Serialize bookings per listing so concurrent requests can't both take the last slot.
    Listing.objects.select_for_update().filter(pk=spec.listing.pk).first()
    check_in, check_out = engine.normalize_dates(spec, data['check_in'], data['check_out'])
    guests = data['guests']
    time_slot = data.get('time_slot') or ''

    # Re-check inside the transaction so two requests can't take the last slot.
    engine.check_availability(spec, check_in, check_out, time_slot, guests)

    pricing = engine.price_for(spec, check_in, check_out, guests)
    total_amount = engine.money(pricing['totalAmount'])
    if data['payment_type'] == PaymentType.FULL:
        amount_paid = total_amount
    else:
        amount_paid = engine.money(total_amount * engine.DEPOSIT_PERCENT / 100)
    amount_due = engine.money(total_amount - amount_paid)
    now = timezone.now()
    if spec.schedule == engine.ScheduleMode.ORDER:
        _take_stock(spec, guests)

    booking = Booking.objects.create(
        reference=_unique_reference(),
        user=user if user and user.is_authenticated else None,
        service_type=spec.service_type,
        service_id=spec.service_id,
        listing_id=spec.listing.listing_id,
        service_name=spec.name,
        location=spec.location,
        image=spec.image or '',
        check_in=check_in,
        check_out=check_out,
        time_slot=time_slot,
        guests=guests,
        unit_price=spec.unit_price,
        guest_full_name=data['guest_full_name'],
        guest_email=data['guest_email'].lower(),
        guest_phone=data.get('guest_phone', ''),
        special_requests=data.get('special_requests') or '',
        payment_type=data['payment_type'],
        payment_method=data['payment_method'],
        payment_status=PaymentStatus.PARTIAL if amount_due > 0 else PaymentStatus.PAID,
        total_amount=total_amount,
        amount_paid=amount_paid,
        amount_due=amount_due,
        deposit_percent=engine.DEPOSIT_PERCENT,
        paid_at=now if amount_paid > 0 else None,
        payment_reference=make_reference(),
        status=BookingStatus.CONFIRMED if amount_paid > 0 else BookingStatus.PENDING_PAYMENT,
        fulfillment=FulfillmentStatus.NOT_STARTED if spec.service_type in FULFILLMENT_SERVICE_TYPES else None,
        created_at=now,
        updated_at=now,
    )

    payment_note = (
        f'Deposit paid: ${_fmt(amount_paid)}. Balance due: ${_fmt(amount_due)}.'
        if amount_due > 0
        else f'Full payment of ${_fmt(amount_paid)} received.'
    )
    # Only the signed-in booker is notified in-app; a typed-in email never routes
    # notifications into someone else's account.
    notify(
        booking.user,
        title='Booking confirmed',
        message=f'{booking.service_name} is reserved under {booking.reference}. {payment_note}',
        type=NotificationType.BOOKING,
        booking=booking,
    )
    notify(
        booking.user,
        title='Payment received',
        message=(
            f'Payment {booking.payment_reference} processed via '
            f'{booking.payment_method.replace("_", " ", 1)}.'
        ),
        type=NotificationType.PAYMENT,
        booking=booking,
    )
    providers = booking_providers(booking)
    for provider in providers:
        notify(
            provider,
            title='New booking received',
            message=(
                f'{booking.guest_full_name} booked {booking.service_name} for {booking.check_in:%Y-%m-%d}'
                f'{f" at {booking.time_slot}" if booking.time_slot else ""} ({booking.reference}).'
            ),
            type=NotificationType.BOOKING,
            booking=booking,
        )
    transaction.on_commit(lambda: send_booking_email(booking))
    transaction.on_commit(lambda: [send_provider_booking_email(booking, p) for p in providers])
    return booking


def _restock(booking: Booking) -> None:
    if booking.service_type != ServiceType.SHOP:
        return
    try:
        spec = engine.resolve(booking.service_type, booking.service_id)
    except ValidationError:
        return
    _return_stock(spec, booking.guests)


@transaction.atomic
def update_status(booking: Booking, status: str, *, by_provider: bool) -> Booking:
    current = booking.status
    if booking.is_archived:
        raise ValidationError({'status': 'This booking is archived.'})
    if status == current:
        return booking
    if status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValidationError(
            {'status': f'A booking that is {current.replace("_", " ")} cannot become {status.replace("_", " ")}.'}
        )

    today = timezone.localdate()
    if not by_provider:
        if status == BookingStatus.CHECKED_IN and today < booking.check_in:
            raise ValidationError({'status': 'You can check in from your arrival date.'})
        if status == BookingStatus.CHECKED_OUT and booking.amount_due > 0:
            raise ValidationError({'status': 'Pay the remaining balance before checking out.'})
        if status == BookingStatus.COMPLETED:
            raise PermissionDenied('Only the service provider can complete a booking.')
        if status == BookingStatus.CONFIRMED:
            raise PermissionDenied('Only the service provider can confirm a booking.')

    now = timezone.now()
    booking.status = status
    booking.updated_at = now
    if status == BookingStatus.CHECKED_IN:
        booking.checked_in_at = now
    if status in (BookingStatus.CHECKED_OUT, BookingStatus.COMPLETED):
        if status == BookingStatus.CHECKED_OUT:
            booking.checked_out_at = now
        # The provider collects any remaining balance at check-out/completion.
        _settle(booking, now)
    if status == BookingStatus.CANCELLED:
        refunded = booking.amount_paid
        booking.amount_refunded = refunded
        booking.amount_paid = ZERO
        booking.amount_due = ZERO
        booking.payment_status = PaymentStatus.REFUNDED if refunded > 0 else PaymentStatus.UNPAID
        _restock(booking)
    booking.save()

    owner = booking.user
    if status == BookingStatus.CHECKED_IN:
        notify(owner, title='Check-in completed',
               message=f'Welcome! You are checked in for {booking.service_name} ({booking.reference}).',
               type=NotificationType.CHECKIN, booking=booking)
    elif status == BookingStatus.CHECKED_OUT:
        notify(owner, title='Check-out completed',
               message=f'Thanks for traveling with Tourista Rwanda. Booking {booking.reference} is checked out.',
               type=NotificationType.CHECKOUT, booking=booking)
    elif status == BookingStatus.CANCELLED:
        refund_note = f' ${_fmt(booking.amount_refunded)} will be refunded.' if booking.amount_refunded > 0 else ''
        notify(owner, title='Booking cancelled',
               message=f'Booking {booking.reference} was cancelled.{refund_note}',
               type=NotificationType.SYSTEM, booking=booking)
        if not by_provider:
            for provider in booking_providers(booking):
                notify(provider, title='Booking cancelled by guest',
                       message=f'{booking.guest_full_name} cancelled {booking.reference}.',
                       type=NotificationType.SYSTEM, booking=booking)
    elif status == BookingStatus.CONFIRMED:
        notify(owner, title='Booking confirmed by provider',
               message=f'{booking.service_name} ({booking.reference}) has been confirmed.',
               type=NotificationType.BOOKING, booking=booking)
    return booking


@transaction.atomic
def pay_balance(booking: Booking, method: str | None = None) -> Booking:
    if booking.is_archived or booking.status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
        raise ValidationError({'status': 'This booking can no longer be paid.'})
    if booking.amount_due <= 0:
        return booking
    now = timezone.now()
    if method:
        booking.payment_method = method
    _settle(booking, now)
    booking.updated_at = now
    if booking.status == BookingStatus.PENDING_PAYMENT:
        booking.status = BookingStatus.CONFIRMED
    booking.save()

    notify(booking.user, title='Balance paid',
           message=f'Remaining balance for {booking.reference} has been paid in full.',
           type=NotificationType.PAYMENT, booking=booking)
    return booking


@transaction.atomic
def update_fulfillment(booking: Booking, fulfillment: str) -> Booking:
    if booking.is_archived or booking.status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
        raise ValidationError({'fulfillment': 'This booking is closed.'})
    if booking.fulfillment is None:
        raise ValidationError({'fulfillment': 'This booking has no fulfillment steps.'})
    track = FULFILLMENT_TRACKS[ServiceType.SHOP if booking.service_type == ServiceType.SHOP else 'service']
    if fulfillment not in track:
        raise ValidationError({'fulfillment': 'This step does not apply to this booking.'})
    if track.index(fulfillment) <= track.index(booking.fulfillment):
        raise ValidationError({'fulfillment': 'Fulfillment can only move forward.'})
    if booking.status == BookingStatus.PENDING_PAYMENT and (
        fulfillment in ACTIVE_FULFILLMENT or fulfillment in FINAL_FULFILLMENT
    ):
        raise ValidationError({'fulfillment': 'Collect a payment or confirm the booking first.'})

    now = timezone.now()
    if fulfillment in FINAL_FULFILLMENT:
        booking.status = BookingStatus.COMPLETED
        booking.checked_out_at = now
        _settle(booking, now)
    elif fulfillment in ACTIVE_FULFILLMENT:
        booking.status = BookingStatus.CHECKED_IN
        booking.checked_in_at = booking.checked_in_at or now
    booking.fulfillment = fulfillment
    booking.updated_at = now
    booking.save()

    notify(booking.user, title='Order update',
           message=f'{booking.service_name} ({booking.reference}) is now: {fulfillment.replace("_", " ")}.',
           type=NotificationType.SYSTEM, booking=booking)
    return booking


def archive(booking: Booking, user) -> Booking:
    booking.is_archived = True
    booking.archived_at = timezone.now()
    booking.archived_by = user
    booking.save(update_fields=['is_archived', 'archived_at', 'archived_by'])
    return booking


def restore(booking: Booking) -> Booking:
    booking.is_archived = False
    booking.archived_at = None
    booking.archived_by = None
    booking.save(update_fields=['is_archived', 'archived_at', 'archived_by'])
    return booking


def claim_guest_bookings(user) -> int:
    """Attach bookings made without an account to a user whose email is now verified."""
    return Booking.objects.filter(user__isnull=True, guest_email__iexact=user.email).update(user=user)
