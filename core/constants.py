"""Enumerations shared across apps. Values mirror the frontend TypeScript types
(`src/types/booking.ts`, `src/contexts/AuthContext.tsx`, `src/config/providerRoles.ts`)."""

from django.db import models


class UserRole(models.TextChoices):
    TOURIST = 'tourist', 'Tourist'
    HOTEL_OWNER = 'hotel_owner', 'Hotel & Accommodation Manager'
    TOUR_OPERATOR = 'tour_operator', 'Tour Guide / Tour Operator'
    ARTISAN = 'artisan', 'Artisan'
    RESTAURANT_OWNER = 'restaurant_owner', 'Restaurant Manager'
    TRANSPORT_OWNER = 'transport_owner', 'Transport Provider'
    PARK_MANAGER = 'park_manager', 'Park Manager'
    DESTINATION_MANAGER = 'destination_manager', 'Destination Manager'
    HISTORY_CULTURE_MANAGER = 'history_culture_manager', 'History & Culture Manager'
    SHOP_OWNER = 'shop_owner', 'Shop & Market Manager'
    SPA_MANAGER = 'spa_manager', 'Massage & Spa Manager'
    ADMIN = 'admin', 'Administrator'


class ServiceType(models.TextChoices):
    DESTINATION = 'destination', 'Destination'
    HOTEL = 'hotel', 'Hotel'
    PARK = 'park', 'Park'
    RESTAURANT = 'restaurant', 'Restaurant'
    TRANSPORT = 'transport', 'Transport'
    SPA = 'spa', 'Massage & Spa'
    ARTISAN = 'artisan', 'Artisan'
    HISTORY_CULTURE = 'history-culture', 'History & Culture'
    SHOP = 'shop', 'Shop'


# Provider roles and the booking service types their dashboard manages
# (`bookingServiceTypes` in providerRoles.ts).
ROLE_BOOKING_SERVICE_TYPES: dict[str, list[str]] = {
    UserRole.HOTEL_OWNER: [ServiceType.HOTEL],
    UserRole.TOUR_OPERATOR: [ServiceType.DESTINATION],
    UserRole.RESTAURANT_OWNER: [ServiceType.RESTAURANT],
    UserRole.TRANSPORT_OWNER: [ServiceType.TRANSPORT],
    UserRole.PARK_MANAGER: [ServiceType.PARK],
    UserRole.DESTINATION_MANAGER: [ServiceType.DESTINATION],
    UserRole.ARTISAN: [ServiceType.ARTISAN],
    UserRole.HISTORY_CULTURE_MANAGER: [ServiceType.HISTORY_CULTURE],
    UserRole.SHOP_OWNER: [ServiceType.SHOP],
    UserRole.SPA_MANAGER: [ServiceType.SPA],
}

# Primary service type of a provider workspace (`ROLE_TO_SERVICE` in providerCatalogStore.ts).
ROLE_TO_SERVICE: dict[str, str] = {role: types[0] for role, types in ROLE_BOOKING_SERVICE_TYPES.items()}

PROVIDER_ROLES = set(ROLE_BOOKING_SERVICE_TYPES)

# Roles that may not be chosen at public signup.
RESTRICTED_SIGNUP_ROLES = {UserRole.ADMIN}


class BookingStatus(models.TextChoices):
    PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
    CONFIRMED = 'confirmed', 'Confirmed'
    CHECKED_IN = 'checked_in', 'Checked In'
    CHECKED_OUT = 'checked_out', 'Checked Out'
    CANCELLED = 'cancelled', 'Cancelled'
    COMPLETED = 'completed', 'Completed'


class FulfillmentStatus(models.TextChoices):
    NOT_STARTED = 'not_started', 'Not started'
    PREPARING = 'preparing', 'Preparing'
    READY = 'ready', 'Ready'
    OUT_FOR_DELIVERY = 'out_for_delivery', 'Out for delivery'
    DELIVERED = 'delivered', 'Delivered'
    IN_SERVICE = 'in_service', 'In service'
    FULFILLED = 'fulfilled', 'Fulfilled'


class PaymentType(models.TextChoices):
    FULL = 'full', 'Full'
    PARTIAL = 'partial', 'Partial'


class PaymentMethod(models.TextChoices):
    CARD = 'card', 'Card'
    MOBILE_MONEY = 'mobile_money', 'Mobile money'
    BANK_TRANSFER = 'bank_transfer', 'Bank transfer'


class PaymentStatus(models.TextChoices):
    UNPAID = 'unpaid', 'Unpaid'
    PARTIAL = 'partial', 'Partial'
    PAID = 'paid', 'Paid'
    REFUNDED = 'refunded', 'Refunded'


class NotificationType(models.TextChoices):
    BOOKING = 'booking', 'Booking'
    PAYMENT = 'payment', 'Payment'
    CHECKIN = 'checkin', 'Check-in'
    CHECKOUT = 'checkout', 'Check-out'
    REMINDER = 'reminder', 'Reminder'
    SYSTEM = 'system', 'System'
