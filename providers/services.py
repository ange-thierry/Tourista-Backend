"""Workspace seeding, ported from `seedWorkspace` in the frontend's providerCatalogStore.ts."""

import json
import re
from functools import lru_cache

from django.conf import settings
from django.db import transaction

from core.constants import ROLE_TO_SERVICE, ServiceType, UserRole
from listings.models import Listing

from .models import AvailabilityRule, CatalogItem, ProviderWorkspace, ScheduleMode, default_time_slots

DEFAULT_IMAGES = [
    'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80',
    'https://images.unsplash.com/photo-1544161515-4ab6ce6db874?auto=format&fit=crop&w=800&q=80',
    'https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=800&q=80',
    'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?auto=format&fit=crop&w=800&q=80',
]

COMPANY_NAMES = {
    UserRole.HOTEL_OWNER: 'Kigali Serena Hotel',
    UserRole.TOUR_OPERATOR: 'Rwanda Trails Tours',
    UserRole.RESTAURANT_OWNER: 'Heaven Restaurant',
    UserRole.TRANSPORT_OWNER: 'Kigali Safari Transfers',
    UserRole.PARK_MANAGER: 'Nyungwe Forest National Park',
    UserRole.DESTINATION_MANAGER: 'Visit Rwanda Destinations',
    UserRole.ARTISAN: 'Inema Art Studio',
    UserRole.HISTORY_CULTURE_MANAGER: 'Kigali Genocide Memorial',
    UserRole.SHOP_OWNER: 'ZANAA Market',
    UserRole.SPA_MANAGER: 'Kigali Wellness Spa',
}

ROLE_SUBTITLES = {
    UserRole.HOTEL_OWNER: 'Manage rooms, overnight stays, guest check-in/out, and room revenue',
    UserRole.TOUR_OPERATOR: 'Manage tour packages, schedules, guides, and traveler bookings',
    UserRole.RESTAURANT_OWNER: 'Manage dining experiences, table reservations, covers, and kitchen service',
    UserRole.TRANSPORT_OWNER: 'Manage fleet, airport transfers, safari hires, and trip status',
    UserRole.PARK_MANAGER: 'Manage park entry, permits, guided activities, and visitor check-in',
    UserRole.DESTINATION_MANAGER: 'Manage destination listings, experiences, and visitor bookings',
    UserRole.ARTISAN: 'Manage workshops, craft products, visitor sessions, and orders',
    UserRole.HISTORY_CULTURE_MANAGER: 'Manage cultural sites, memorials, guided visits, and tickets',
    UserRole.SHOP_OWNER: 'Manage products, stock, customer orders, payments, and deliveries',
    UserRole.SPA_MANAGER: 'Manage treatments, therapists, appointment slots, and wellness packages',
}


@lru_cache(maxsize=1)
def provider_samples() -> dict:
    path = settings.BASE_DIR / 'seed_data' / 'provider_samples.json'
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def default_schedule_mode(role: str) -> str:
    if role in (UserRole.HOTEL_OWNER, UserRole.TRANSPORT_OWNER):
        return ScheduleMode.OVERNIGHT
    if role == UserRole.SHOP_OWNER:
        return ScheduleMode.ORDER
    return ScheduleMode.DAY_VISIT


def parse_price(price: str) -> float:
    digits = re.sub(r'[^0-9.]', '', str(price))
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0


def _price_label(price: str, mode: str) -> str:
    if '/' in price:
        return '/'.join(price.split('/')[1:]).strip() or 'per person'
    return {ScheduleMode.OVERNIGHT: 'per night', ScheduleMode.ORDER: 'per item'}.get(mode, 'per person')


def _pick_listing_id(service_type: str, company_name: str, exclude_ws: int | None = None) -> int:
    taken = set(
        ProviderWorkspace.objects.filter(service_type=service_type)
        .exclude(pk=exclude_ws)
        .values_list('linked_listing_id', flat=True)
    )
    listings = Listing.objects.filter(service_type=service_type).order_by('listing_id')
    named = listings.filter(name__iexact=company_name).first()
    if named and named.listing_id not in taken:
        return named.listing_id
    for listing_id in listings.values_list('listing_id', flat=True):
        if listing_id not in taken:
            return listing_id
    return 1


def listing_taken(service_type: str, listing_id: int, workspace: ProviderWorkspace) -> bool:
    return (
        ProviderWorkspace.objects.filter(service_type=service_type, linked_listing_id=listing_id)
        .exclude(pk=workspace.pk)
        .exists()
    )


@transaction.atomic
def get_or_seed_workspace(user) -> ProviderWorkspace:
    existing = ProviderWorkspace.objects.filter(user=user, role=user.role).first()
    if existing:
        return existing

    role = user.role
    mode = default_schedule_mode(role)
    service_type = ROLE_TO_SERVICE.get(role, ServiceType.DESTINATION)
    company_name = COMPANY_NAMES.get(role, 'My Company')

    ws = ProviderWorkspace.objects.create(
        user=user,
        role=role,
        service_type=service_type,
        company_name=company_name,
        description=ROLE_SUBTITLES.get(role, 'Manage your Tourista listing.'),
        location='Kigali',
        province='Kigali',
        hours='08:00 AM - 08:00 PM',
        phone='+250 7XX XXX XXX',
        amenities=['WiFi', 'Parking', 'Customer support'],
        image=DEFAULT_IMAGES[0],
        linked_listing_id=_pick_listing_id(service_type, company_name),
    )

    for index, sample in enumerate(provider_samples().get(role, [])):
        CatalogItem.objects.create(
            # Sample ids (h1, t2, ...) are only unique per role; prefix with the user.
            id=f'u{user.pk}-{sample["id"]}',
            workspace=ws,
            name=sample['name'],
            description=sample['description'],
            category=sample['category'],
            price=parse_price(sample['price']),
            price_label=_price_label(sample['price'], mode),
            image=DEFAULT_IMAGES[index % len(DEFAULT_IMAGES)],
            status=sample['status'],
            schedule_mode=mode,
            duration_minutes=60 if mode == ScheduleMode.DAY_VISIT else None,
            capacity=2 if mode == ScheduleMode.OVERNIGHT else 8,
            stock=12 if mode == ScheduleMode.ORDER else None,
            available_count=3 if mode == ScheduleMode.OVERNIGHT else 4,
            total_count=5 if mode == ScheduleMode.OVERNIGHT else 6,
            amenities=[],
            position=index,
        )

    AvailabilityRule.objects.create(
        id=AvailabilityRule.new_id(),
        workspace=ws,
        item_id='all',
        open_time_slots=default_time_slots(),
        capacity_per_day=4,
        notes='Default company availability',
    )
    return ws
