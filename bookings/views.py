import csv
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.constants import BookingStatus, ServiceType

from . import engine, services
from .models import Booking, Notification
from .serializers import (
    CreateBookingSerializer,
    FulfillmentSerializer,
    PayBalanceSerializer,
    QuoteSerializer,
    StatusSerializer,
    booking_to_frontend,
    booking_to_occupancy,
    notification_to_frontend,
)

MAX_PAGE_SIZE = 200


def manages(user, booking: Booking) -> bool:
    if user.is_platform_admin:
        return True
    if not user.is_provider:
        return False
    return Booking.objects.filter(engine.provider_scope_q(user), pk=booking.pk).exists()


def owns(user, booking: Booking) -> bool:
    return booking.user_id == user.pk


def visible_bookings(user, *, include_archived: bool = False):
    """Admins see everything; providers see their listing's bookings plus their own
    trips; everyone else sees only bookings made while signed in to their account."""
    if user.is_platform_admin:
        qs = Booking.objects.all()
    elif user.is_provider:
        qs = Booking.objects.filter(Q(user=user) | engine.provider_scope_q(user))
    else:
        qs = Booking.objects.filter(user=user)
    return qs if include_archived else qs.filter(is_archived=False)


def get_booking_for(user, pk: str, *, manage: bool = False) -> Booking:
    booking = get_object_or_404(Booking, pk=pk)
    if manages(user, booking):
        return booking
    if not manage and owns(user, booking):
        return booking
    raise PermissionDenied('You cannot access this booking.')


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise ValidationError({'date': f'Invalid date "{value}". Use YYYY-MM-DD.'})


def filter_bookings(qs, params, user):
    if service_type := params.get('service_type'):
        qs = qs.filter(service_type__in=service_type.split(','))
    if status_value := params.get('status'):
        qs = qs.filter(status__in=status_value.split(','))
    if params.get('mine') in ('1', 'true'):
        qs = qs.filter(user=user)
    if params.get('archived') in ('1', 'true'):
        qs = qs.filter(is_archived=True)
    if start := _parse_date(params.get('from')):
        qs = qs.filter(check_out__gte=start)
    if end := _parse_date(params.get('to')):
        qs = qs.filter(check_in__lte=end)
    if search := params.get('search', '').strip():
        qs = qs.filter(
            Q(reference__icontains=search)
            | Q(guest_full_name__icontains=search)
            | Q(guest_email__icontains=search)
            | Q(service_name__icontains=search)
        )
    return qs


def paginate(request, qs, serialize):
    """`?page=N&page_size=M` returns {count, page, pageSize, hasMore, results};
    without `page` the full (filtered) list is returned as a plain array."""
    page_param = request.query_params.get('page')
    if page_param is None:
        return Response([serialize(item) for item in qs])
    try:
        page = max(int(page_param), 1)
        size = min(max(int(request.query_params.get('page_size', 50)), 1), MAX_PAGE_SIZE)
    except ValueError:
        raise ValidationError({'page': 'page and page_size must be numbers.'})
    count = qs.count()
    start = (page - 1) * size
    items = list(qs[start:start + size])
    return Response(
        {
            'count': count,
            'page': page,
            'pageSize': size,
            'hasMore': start + len(items) < count,
            'results': [serialize(item) for item in items],
        }
    )


class BookingListCreateView(APIView):
    """GET: bookings visible to the signed-in user. POST: create a booking (guests allowed)."""

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_throttles(self):
        if self.request.method == 'POST':
            self.throttle_scope = 'booking_create'
            return [ScopedRateThrottle()]
        return []

    def get(self, request):
        include_archived = request.query_params.get('archived') in ('1', 'true')
        qs = visible_bookings(request.user, include_archived=include_archived)
        qs = filter_bookings(qs, request.query_params, request.user)
        return paginate(request, qs, booking_to_frontend)

    def post(self, request):
        serializer = CreateBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.create_booking(serializer.to_service_input(), user=request.user)
        return Response(booking_to_frontend(booking), status=status.HTTP_201_CREATED)


class BookingQuoteView(APIView):
    """Authoritative price and availability before the guest pays."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = QuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(services.quote(serializer.to_service_input()))


class AvailabilityView(APIView):
    """Calendar data for one bookable option.

    `?service_type=spa&service_id=1:hot-stone&from=YYYY-MM-DD&to=YYYY-MM-DD[&date=YYYY-MM-DD]`
    → `{schedule, inventory, slotCapacity, days: {date: free|limited|full}, slots?: [...]}`
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        params = request.query_params
        service_type = params.get('service_type', '')
        if service_type not in ServiceType.values:
            raise ValidationError({'service_type': 'Unknown service type.'})
        spec = engine.resolve(service_type, params.get('service_id', ''))
        today = timezone.localdate()
        start = max(_parse_date(params.get('from')) or today, today)
        end = _parse_date(params.get('to')) or start + timedelta(days=90)
        end = min(end, start + timedelta(days=engine.BOOKING_WINDOW_DAYS))
        data = {
            'serviceName': spec.name,
            'schedule': spec.schedule,
            'pricingMode': spec.pricing_mode,
            'unitPrice': float(spec.unit_price),
            'inventory': spec.inventory,
            'slotCapacity': spec.slot_capacity,
            'stock': spec.stock,
            'days': engine.calendar(spec, start, end),
        }
        if day := _parse_date(params.get('date')):
            data['slots'] = engine.slots_for(spec, day)
        return Response(data)


class BookingDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        return Response(booking_to_frontend(get_booking_for(request.user, pk)))

    def delete(self, request, pk):
        """Archive (soft-delete). The record stays for accounting and can be restored."""
        booking = get_booking_for(request.user, pk, manage=True)
        services.archive(booking, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BookingRestoreView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        booking = get_booking_for(request.user, pk, manage=True)
        return Response(booking_to_frontend(services.restore(booking)))


class BookingStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = StatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = get_booking_for(request.user, pk)
        booking = services.update_status(
            booking, serializer.validated_data['status'], by_provider=manages(request.user, booking)
        )
        return Response(booking_to_frontend(booking))


class BookingPayBalanceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = PayBalanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = get_booking_for(request.user, pk)
        booking = services.pay_balance(booking, serializer.validated_data.get('method'))
        return Response(booking_to_frontend(booking))


class BookingFulfillmentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = FulfillmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = get_booking_for(request.user, pk, manage=True)
        booking = services.update_fulfillment(booking, serializer.validated_data['fulfillment'])
        return Response(booking_to_frontend(booking))


class BookingLookupView(APIView):
    """Let a guest without an account find a booking by reference + email."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'lookup'

    def get(self, request):
        reference = request.query_params.get('reference', '').strip()
        email = request.query_params.get('email', '').strip()
        booking = get_object_or_404(
            Booking, reference__iexact=reference, guest_email__iexact=email, is_archived=False
        )
        return Response(booking_to_frontend(booking))


class OccupancyView(APIView):
    """Public, anonymised bookings (kept for backwards compatibility; calendars use /availability/)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = Booking.objects.filter(
            is_archived=False, status__in=engine.OCCUPYING_STATUSES, check_out__gte=timezone.localdate()
        )
        if service_type := request.query_params.get('service_type'):
            qs = qs.filter(service_type=service_type)
        if (listing_id := request.query_params.get('listing_id', '')).isdigit():
            qs = qs.filter(listing_id=int(listing_id))
        return Response([booking_to_occupancy(b) for b in qs[:1000]])


def booking_stats(qs) -> dict:
    totals = qs.aggregate(
        revenue=Sum('amount_paid'), due=Sum('amount_due'), refunded=Sum('amount_refunded'), count=Count('id')
    )
    by_status = {row['status']: row['n'] for row in qs.values('status').annotate(n=Count('id'))}
    by_type = {row['service_type']: row['n'] for row in qs.values('service_type').annotate(n=Count('id'))}
    by_month = [
        {
            'month': row['month'].strftime('%Y-%m'),
            'bookings': row['n'],
            'revenue': float(row['revenue'] or 0),
        }
        for row in qs.annotate(month=TruncMonth('check_in'))
        .values('month')
        .annotate(n=Count('id'), revenue=Sum('amount_paid'))
        .order_by('month')
    ]
    by_method = {
        row['payment_method']: float(row['total'] or 0)
        for row in qs.values('payment_method').annotate(total=Sum('amount_paid'))
    }
    by_option = [
        {'name': row['service_name'], 'bookings': row['n'], 'revenue': float(row['revenue'] or 0)}
        for row in qs.values('service_name')
        .annotate(n=Count('id'), revenue=Sum('amount_paid'))
        .order_by('-revenue')[:10]
    ]
    return {
        'bookings': totals['count'] or 0,
        'revenue': float(totals['revenue'] or 0),
        'due': float(totals['due'] or 0),
        'refunded': float(totals['refunded'] or 0),
        'byStatus': {value: by_status.get(value, 0) for value in BookingStatus.values},
        'byServiceType': by_type,
        'byMonth': by_month,
        'byPaymentMethod': by_method,
        'topOptions': by_option,
    }


class BookingStatsView(APIView):
    """Aggregates for dashboards over the bookings the user manages (or owns)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = visible_bookings(request.user)
        if request.user.is_provider and request.query_params.get('mine') not in ('1', 'true'):
            qs = qs.filter(engine.provider_scope_q(request.user))
        qs = filter_bookings(qs, request.query_params, request.user)
        return Response(booking_stats(qs))


class BookingExportView(APIView):
    """CSV of bookings for reports and accounting (providers and admins)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not (request.user.is_provider or request.user.is_platform_admin):
            raise PermissionDenied('Only providers and admins can export bookings.')
        qs = visible_bookings(request.user, include_archived=request.query_params.get('archived') in ('1', 'true'))
        if request.user.is_provider:
            qs = qs.filter(engine.provider_scope_q(request.user))
        qs = filter_bookings(qs, request.query_params, request.user)

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="bookings-{timezone.localdate()}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Reference', 'Service', 'Type', 'Guest', 'Email', 'Phone', 'Check-in', 'Check-out', 'Time',
            'Guests/Qty', 'Status', 'Fulfillment', 'Payment status', 'Method', 'Total', 'Paid', 'Due',
            'Refunded', 'Created', 'Archived',
        ])
        for b in qs.iterator():
            writer.writerow([
                b.reference, b.service_name, b.service_type, b.guest_full_name, b.guest_email, b.guest_phone,
                b.check_in, b.check_out, b.time_slot, b.guests, b.status, b.fulfillment or '',
                b.payment_status, b.payment_method, b.total_amount, b.amount_paid, b.amount_due,
                b.amount_refunded, timezone.localtime(b.created_at).strftime('%Y-%m-%d %H:%M'),
                'yes' if b.is_archived else '',
            ])
        return response


class NotificationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(user=request.user)
        if request.query_params.get('unread') in ('1', 'true'):
            qs = qs.filter(read=False)
        if request.query_params.get('page') is None:
            qs = qs[:100]
        return paginate(request, qs, notification_to_frontend)


class NotificationReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        updated = Notification.objects.filter(user=request.user, pk=pk).update(read=True)
        if not updated:
            return Response({'message': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationReadAllView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(user=request.user, read=False).update(read=True)
        return Response(status=status.HTTP_204_NO_CONTENT)
