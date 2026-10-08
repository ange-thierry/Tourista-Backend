"""Server-side pricing and availability.

Every booking names what it books with `service_type` + `service_id`, where
`service_id` is `<listing id>` or `<listing id>:<facility id>`. The facility is
either a provider catalog item (managed in the provider dashboard) or a public
facility from the seeded catalog (`listings.Facility`). Prices, capacity and
stock always come from those records, never from the client.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.constants import BookingStatus, ServiceType
from listings.models import Facility, Listing
from providers.models import AvailabilityRule, CatalogItem, CatalogItemStatus, ProviderWorkspace, ScheduleMode

from .models import Booking

CENT = Decimal('0.01')
DEPOSIT_PERCENT = 30
BOOKING_WINDOW_DAYS = 365
DEFAULT_TIME_SLOTS = [f'{hour:02d}:00' for hour in range(8, 20)]

# Bookings that still occupy a room/slot/vehicle.
OCCUPYING_STATUSES = [BookingStatus.PENDING_PAYMENT, BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]

# Guests that fit in one time slot when nothing more specific is configured.
DEFAULT_SLOT_CAPACITY = {
    ServiceType.SPA: 2,
    ServiceType.ARTISAN: 12,
    ServiceType.RESTAURANT: 40,
    ServiceType.PARK: 60,
    ServiceType.DESTINATION: 30,
    ServiceType.HISTORY_CULTURE: 60,
    ServiceType.HOTEL: 10,
}
# Units (rooms, vehicles) per overnight facility when the catalog doesn't say.
DEFAULT_INVENTORY = {ServiceType.HOTEL: 1, ServiceType.TRANSPORT: 2}

# Listing-level prices in the bundled catalog: (field, divisor to convert to USD).
# Restaurant and transport prices are in RWF; the UI shows them converted the same way.
BASE_PRICE_FIELDS = {
    ServiceType.HOTEL: ('pricePerNight', 1),
    ServiceType.DESTINATION: ('price', 1),
    ServiceType.PARK: ('entryFee', 1),
    ServiceType.HISTORY_CULTURE: ('entryFee', 1),
    ServiceType.RESTAURANT: ('averageCost', 1000),
    ServiceType.TRANSPORT: ('pricePerDay', 1200),
    ServiceType.SPA: ('priceFrom', 1),
}
ARTISAN_WORKSHOP_FEE = Decimal('25')


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def slot_start(time_slot: str | None) -> str:
    """'10:00 – 11:00' -> '10:00'."""
    return (time_slot or '').strip()[:5]


@dataclass
class ServiceSpec:
    service_type: str
    service_id: str
    listing: Listing
    name: str
    location: str
    image: str
    unit_price: Decimal
    pricing_mode: str  # 'per_night' | 'per_guest'
    schedule: str  # 'overnight' | 'day_visit' | 'order'
    inventory: int
    slot_capacity: int
    max_guests: int | None = None
    workspace: ProviderWorkspace | None = None
    catalog_item: CatalogItem | None = None
    facility: Facility | None = None
    rule: AvailabilityRule | None = None
    option_name: str = ''
    notes: list[str] = field(default_factory=list)

    @property
    def stock_holder(self):
        """Object whose `stock` field limits orders, or None for unlimited."""
        if self.catalog_item is not None and self.catalog_item.stock is not None:
            return self.catalog_item
        if self.facility is not None and self.facility.stock is not None:
            return self.facility
        return None

    @property
    def stock(self) -> int | None:
        holder = self.stock_holder
        return holder.stock if holder is not None else None

    @property
    def open_slots(self) -> list[str]:
        if self.rule and self.rule.open_time_slots:
            return sorted(self.rule.open_time_slots)
        return DEFAULT_TIME_SLOTS

    @property
    def closed_slots(self) -> set[str]:
        return set(self.rule.closed_time_slots) if self.rule else set()


def _base_price(listing: Listing) -> Decimal | None:
    if listing.service_type == ServiceType.ARTISAN:
        return ARTISAN_WORKSHOP_FEE
    spec = BASE_PRICE_FIELDS.get(listing.service_type)
    if not spec:
        return None
    field_name, divisor = spec
    raw = listing.data.get(field_name)
    if raw is None:
        return None
    return money(Decimal(str(raw)) / divisor)


def _with_province(location: str, province: str) -> str:
    if province and province.lower() not in location.lower():
        return f'{location}, {province}' if location else province
    return location


def resolve(service_type: str, service_id) -> ServiceSpec:
    """Look up what is being booked and its authoritative price/capacity."""
    service_id = str(service_id).strip()
    head, _, option_id = service_id.partition(':')
    if not head.isdigit():
        raise ValidationError({'serviceId': 'Unknown service.'})
    listing = Listing.objects.filter(
        service_type=service_type, listing_id=int(head), is_published=True
    ).first()
    if listing is None:
        raise ValidationError({'serviceId': 'This listing does not exist or is not bookable.'})

    workspace = (
        ProviderWorkspace.objects.filter(service_type=service_type, linked_listing_id=listing.listing_id)
        .select_related('user')
        .first()
    )
    company_name = workspace.company_name if workspace else listing.name
    base = _base_price(listing)
    overnight_type = service_type in (ServiceType.HOTEL, ServiceType.TRANSPORT)

    catalog_item = facility = None
    if option_id and workspace:
        catalog_item = workspace.catalog.filter(pk=option_id, status=CatalogItemStatus.ACTIVE).first()
    if option_id and catalog_item is None:
        facility = Facility.objects.filter(
            service_type=service_type, listing_id=listing.listing_id, facility_id=option_id
        ).first()
        if facility is None:
            raise ValidationError({'serviceId': 'This option is not available for booking.'})

    if catalog_item is not None:
        mode = catalog_item.schedule_mode
        unit_price = money(catalog_item.price)
        option_name = catalog_item.name
        image = catalog_item.image
        inventory = catalog_item.total_count or catalog_item.available_count or 1
        slot_capacity = catalog_item.capacity or DEFAULT_SLOT_CAPACITY.get(service_type, 10)
        max_guests = catalog_item.capacity if mode == ScheduleMode.OVERNIGHT else None
    elif facility is not None:
        if service_type == ServiceType.SHOP:
            mode = ScheduleMode.ORDER
        elif facility.kind == Facility.Kind.ROOM or service_type == ServiceType.TRANSPORT:
            mode = ScheduleMode.OVERNIGHT
        else:
            mode = ScheduleMode.DAY_VISIT
        price = facility.price if facility.price is not None else base
        if price is None:
            raise ValidationError({'serviceId': 'This option has no price yet.'})
        unit_price = money(price)
        option_name = facility.name
        image = facility.image
        inventory = facility.inventory or DEFAULT_INVENTORY.get(service_type, 1)
        slot_capacity = facility.capacity or DEFAULT_SLOT_CAPACITY.get(service_type, 10)
        max_guests = facility.capacity if mode == ScheduleMode.OVERNIGHT else None
    else:
        if service_type == ServiceType.SHOP or base is None:
            raise ValidationError({'serviceId': 'Choose a specific product or option to book.'})
        mode = ScheduleMode.OVERNIGHT if overnight_type else ScheduleMode.DAY_VISIT
        unit_price = base
        option_name = ''
        image = listing.image
        inventory = DEFAULT_INVENTORY.get(service_type, 1)
        slot_capacity = DEFAULT_SLOT_CAPACITY.get(service_type, 10)
        max_guests = None

    rule = None
    if workspace:
        rules = list(workspace.availability.all())
        option_key = option_id or ''
        rule = next((r for r in rules if option_key and r.item_id == option_key), None) or next(
            (r for r in rules if r.item_id == 'all'), None
        )

    return ServiceSpec(
        service_type=service_type,
        service_id=service_id,
        listing=listing,
        name=f'{company_name} · {option_name}' if option_name else company_name,
        location=_with_province(listing.location, listing.province),
        image=image or listing.image,
        unit_price=unit_price,
        pricing_mode='per_night' if mode == ScheduleMode.OVERNIGHT else 'per_guest',
        schedule=mode,
        inventory=max(int(inventory), 1),
        slot_capacity=max(int(slot_capacity), 1),
        max_guests=max_guests,
        workspace=workspace,
        catalog_item=catalog_item,
        facility=facility,
        rule=rule,
        option_name=option_name,
    )


# --- availability -------------------------------------------------------------


def occupying_bookings(spec: ServiceSpec, start: date, end: date, exclude_id: str | None = None):
    qs = Booking.objects.filter(
        service_type=spec.service_type,
        service_id=spec.service_id,
        is_archived=False,
        status__in=OCCUPYING_STATUSES,
        check_in__lte=end,
        check_out__gte=start,
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return list(qs.only('id', 'check_in', 'check_out', 'time_slot', 'guests'))


def _occupies(booking: Booking, day: date) -> bool:
    if booking.check_out <= booking.check_in:
        return booking.check_in == day
    return booking.check_in <= day < booking.check_out


def _slot_usage(spec: ServiceSpec, day: date, bookings) -> dict[str, int]:
    usage: dict[str, int] = {}
    for b in bookings:
        if b.check_in == day and b.time_slot:
            key = slot_start(b.time_slot)
            usage[key] = usage.get(key, 0) + b.guests
    return usage


def slots_for(spec: ServiceSpec, day: date, bookings=None) -> list[dict]:
    """Time slots for a day with remaining guest capacity."""
    if bookings is None:
        bookings = occupying_bookings(spec, day, day)
    usage = _slot_usage(spec, day, bookings)
    blocked_day = bool(spec.rule and day.isoformat() in spec.rule.blocked_dates)
    now = timezone.localtime()
    slots = []
    opens = spec.open_slots
    for index, time in enumerate(opens):
        end_time = opens[index + 1] if index + 1 < len(opens) else '20:00'
        remaining = max(spec.slot_capacity - usage.get(time, 0), 0)
        if blocked_day or time in spec.closed_slots:
            status, note = 'closed', 'Closed by the provider'
        elif day == now.date() and time <= now.strftime('%H:%M'):
            status, note = 'closed', 'Time has passed'
        elif remaining <= 0:
            status, note = 'full', 'Fully booked'
        elif remaining < spec.slot_capacity:
            status, note = 'limited', f'{remaining} place{"s" if remaining != 1 else ""} left'
        else:
            status, note = 'free', 'Available'
        slots.append({'time': time, 'endTime': end_time, 'status': status, 'remaining': remaining, 'note': note})
    return slots


def day_status(spec: ServiceSpec, day: date, bookings) -> str:
    """'free' | 'limited' | 'full' for one calendar day."""
    key = day.isoformat()
    if day < timezone.localdate():
        return 'full'
    if spec.rule and key in spec.rule.blocked_dates:
        return 'full'
    limited = bool(spec.rule and key in spec.rule.limited_dates)

    if spec.schedule == ScheduleMode.OVERNIGHT:
        used = sum(1 for b in bookings if _occupies(b, day))
        if used >= spec.inventory:
            return 'full'
        return 'limited' if used or limited else 'free'

    day_bookings = [b for b in bookings if b.check_in == day]
    if spec.rule and spec.rule.capacity_per_day and len(day_bookings) >= spec.rule.capacity_per_day:
        return 'full'
    if spec.schedule == ScheduleMode.ORDER:
        if spec.stock is not None and spec.stock <= 0:
            return 'full'
        return 'limited' if day_bookings or limited else 'free'

    slots = slots_for(spec, day, bookings)
    if not any(slot['status'] in ('free', 'limited') for slot in slots):
        return 'full'
    if limited or any(slot['status'] == 'limited' for slot in slots) or day_bookings:
        return 'limited'
    return 'free'


def calendar(spec: ServiceSpec, start: date, end: date) -> dict[str, str]:
    bookings = occupying_bookings(spec, start, end)
    days = {}
    day = start
    while day <= end:
        days[day.isoformat()] = day_status(spec, day, bookings)
        day += timedelta(days=1)
    return days


def nights_between(check_in: date, check_out: date) -> int:
    return max((check_out - check_in).days, 1)


def price_for(spec: ServiceSpec, check_in: date, check_out: date, guests: int) -> dict:
    units = nights_between(check_in, check_out) if spec.pricing_mode == 'per_night' else guests
    total = money(spec.unit_price * units)
    return {
        'unitPrice': float(spec.unit_price),
        'pricingMode': spec.pricing_mode,
        'units': units,
        'nights': nights_between(check_in, check_out) if spec.pricing_mode == 'per_night' else 0,
        'totalAmount': float(total),
        'depositPercent': DEPOSIT_PERCENT,
        'depositAmount': float(money(total * DEPOSIT_PERCENT / 100)),
        'currency': 'USD',
    }


def normalize_dates(spec: ServiceSpec, check_in: date, check_out: date) -> tuple[date, date]:
    if spec.schedule == ScheduleMode.OVERNIGHT:
        return check_in, check_out
    # Day visits and orders occupy a single date.
    return check_in, check_in


def check_availability(
    spec: ServiceSpec,
    check_in: date,
    check_out: date,
    time_slot: str | None,
    guests: int,
    exclude_id: str | None = None,
) -> None:
    """Raise ValidationError with a user-facing message when the request can't be booked."""
    today = timezone.localdate()
    if check_in < today:
        raise ValidationError({'checkIn': 'This date is in the past.'})
    if check_in > today + timedelta(days=BOOKING_WINDOW_DAYS):
        raise ValidationError({'checkIn': 'Bookings open up to one year ahead.'})
    if spec.max_guests and guests > spec.max_guests:
        raise ValidationError({'guests': f'This option fits at most {spec.max_guests} guests.'})

    bookings = occupying_bookings(spec, check_in, check_out, exclude_id)

    if spec.schedule == ScheduleMode.OVERNIGHT:
        if check_out <= check_in:
            raise ValidationError({'checkOut': 'Check-out must be after check-in.'})
        day = check_in
        while day < check_out:
            if day_status(spec, day, bookings) == 'full':
                raise ValidationError({'checkIn': f'Not available on {day:%d %b %Y}. Choose other dates.'})
            day += timedelta(days=1)
        return

    if day_status(spec, check_in, bookings) == 'full':
        raise ValidationError({'checkIn': f'{check_in:%d %b %Y} is fully booked or closed.'})

    if spec.schedule == ScheduleMode.ORDER:
        if spec.stock is not None and guests > spec.stock:
            raise ValidationError({'guests': f'Only {max(spec.stock, 0)} left in stock.'})
        if time_slot and slot_start(time_slot) in spec.closed_slots:
            raise ValidationError({'timeSlot': 'This delivery window is closed.'})
        return

    start = slot_start(time_slot)
    if not start:
        raise ValidationError({'timeSlot': 'Choose a time slot.'})
    slot = next((s for s in slots_for(spec, check_in, bookings) if s['time'] == start), None)
    if slot is None or slot['status'] == 'closed':
        raise ValidationError({'timeSlot': 'This time slot is not open.'})
    if slot['remaining'] < guests:
        left = slot['remaining']
        raise ValidationError(
            {'timeSlot': f'Only {left} place{"s" if left != 1 else ""} left at {start}.' if left else f'{start} is fully booked.'}
        )


def provider_scope_q(user) -> Q:
    """Bookings a provider manages: their service types at their linked listing."""
    from core.constants import ROLE_BOOKING_SERVICE_TYPES
    from providers.services import get_or_seed_workspace

    types = ROLE_BOOKING_SERVICE_TYPES.get(user.role, [])
    if not types:
        return Q(pk__in=[])
    ws = get_or_seed_workspace(user)
    return Q(service_type__in=types, listing_id=ws.linked_listing_id)
