from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .constants import (
    PROVIDER_ROLES,
    ROLE_BOOKING_SERVICE_TYPES,
    BookingStatus,
    FulfillmentStatus,
    PaymentMethod,
    ServiceType,
    UserRole,
)


@api_view(['GET'])
@permission_classes([AllowAny])
def health(request):
    return Response({'status': 'ok', 'time': timezone.now().isoformat()})


@api_view(['GET'])
@permission_classes([AllowAny])
def meta(request):
    """Enumerations the frontend can use for selects and labels."""

    def choices(enum):
        return [{'value': value, 'label': label} for value, label in enum.choices]

    return Response(
        {
            'roles': choices(UserRole),
            'providerRoles': sorted(PROVIDER_ROLES),
            'roleServiceTypes': ROLE_BOOKING_SERVICE_TYPES,
            'serviceTypes': choices(ServiceType),
            'bookingStatuses': choices(BookingStatus),
            'fulfillmentStatuses': choices(FulfillmentStatus),
            'paymentMethods': choices(PaymentMethod),
        }
    )
