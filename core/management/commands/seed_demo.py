"""Load the frontend's catalog data, demo accounts and demo bookings into the database.

    python manage.py seed_demo            # idempotent: upserts everything
    python manage.py seed_demo --reset    # also wipes bookings/notifications first

The JSON files in `seed_data/` were exported from the frontend `src/data/*.ts`.
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking, Notification
from core.constants import UserRole
from listings.models import Facility, Listing, ReferenceData
from providers.models import ProviderWorkspace
from providers.services import get_or_seed_workspace
from reviews.views import refresh_listing_rating

SEED_DIR = settings.BASE_DIR / 'seed_data'

DEMO_ACCOUNTS = [
    ('tourist@tourista.rw', 'Demo Tourist', UserRole.TOURIST),
    ('hotel@tourista.rw', 'Hotel Manager', UserRole.HOTEL_OWNER),
    ('tour@tourista.rw', 'Tour Operator', UserRole.TOUR_OPERATOR),
    ('restaurant@tourista.rw', 'Restaurant Manager', UserRole.RESTAURANT_OWNER),
    ('transport@tourista.rw', 'Transport Provider', UserRole.TRANSPORT_OWNER),
    ('park@tourista.rw', 'Park Manager', UserRole.PARK_MANAGER),
    ('destination@tourista.rw', 'Destination Manager', UserRole.DESTINATION_MANAGER),
    ('culture@tourista.rw', 'History & Culture Manager', UserRole.HISTORY_CULTURE_MANAGER),
    ('artisan@tourista.rw', 'Artisan Studio', UserRole.ARTISAN),
    ('shop@tourista.rw', 'Shop Manager', UserRole.SHOP_OWNER),
    ('spa@tourista.rw', 'Spa Manager', UserRole.SPA_MANAGER),
    ('admin@tourista.rw', 'Platform Admin', UserRole.ADMIN),
]


def _load(name: str):
    with open(SEED_DIR / name, encoding='utf-8') as fh:
        return json.load(fh)


def _parse_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class Command(BaseCommand):
    help = 'Seed listings, demo accounts, provider workspaces and demo bookings.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete all bookings and notifications first.')
        parser.add_argument('--no-bookings', action='store_true', help='Skip demo bookings.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            Notification.objects.all().delete()
            Booking.objects.all().delete()
            self.stdout.write('Cleared bookings and notifications.')

        self._seed_listings()
        users = self._seed_accounts()
        for user in users:
            if user.is_provider:
                get_or_seed_workspace(user)
        self.stdout.write(f'Provider workspaces ready for {sum(u.is_provider for u in users)} accounts.')
        if not options['no_bookings']:
            self._seed_bookings()
        self.stdout.write(self.style.SUCCESS('Seed complete.'))

    def _seed_listings(self):
        payload = _load('listings.json')
        count = 0
        for service_type, items in payload['listings'].items():
            for item in items:
                columns, extra = Listing.split_payload(item)
                listing, _ = Listing.objects.update_or_create(
                    service_type=service_type,
                    listing_id=item['id'],
                    defaults={
                        **columns,
                        'data': extra,
                        'base_rating': item.get('rating', 0),
                        'base_reviews': item.get('reviews', 0),
                    },
                )
                # Keep guest reviews counted after a re-seed.
                refresh_listing_rating(service_type, listing.listing_id)
                count += 1
        ReferenceData.objects.update_or_create(
            key='spaTreatmentsCatalog', defaults={'data': payload['spaTreatmentsCatalog']}
        )
        ReferenceData.objects.update_or_create(key='shopCategories', defaults={'data': payload['shopCategories']})
        self.stdout.write(f'Listings upserted: {count}.')
        self._seed_facilities()

    def _seed_facilities(self):
        rows = _load('facilities.json')
        for row in rows:
            facility, created = Facility.objects.update_or_create(
                service_type=row['serviceType'],
                listing_id=row['listingId'],
                facility_id=row['facilityId'],
                defaults={
                    'name': row['name'],
                    'kind': row['kind'],
                    'price': row['price'],
                    'price_label': row.get('priceLabel') or '',
                    'image': row.get('image') or '',
                    'capacity': row.get('capacity'),
                    'inventory': row.get('inventory'),
                },
            )
            # Products start with their listed stock; later re-seeds keep the live count.
            if created and row['kind'] == 'product':
                facility.stock = row.get('inventory') or 20
                facility.save(update_fields=['stock'])
        self.stdout.write(f'Facilities upserted: {len(rows)}.')

    def _seed_accounts(self) -> list[User]:
        users = []
        for email, name, role in DEMO_ACCOUNTS:
            user, created = User.objects.get_or_create(
                email=email, defaults={'name': name, 'role': role, 'email_verified': True}
            )
            if created:
                user.set_password(settings.DEMO_PASSWORD)
                if role == UserRole.ADMIN:
                    user.is_staff = True
                    user.is_superuser = True
                user.save()
            users.append(user)
        self.stdout.write(f'Demo accounts ready ({len(users)}), password: {settings.DEMO_PASSWORD}')
        return users

    def _seed_bookings(self):
        payload = _load('demo_bookings.json')
        # Keep demo bookings relative to "today" no matter when the seed runs.
        exported = _parse_dt(payload['exportedAt'])
        shift = timezone.localdate() - timezone.localtime(exported).date()
        shift_dt = timedelta(days=shift.days)

        # Providers only see bookings for their own listing, so point each demo booking
        # at the listing of a demo provider for that service type.
        listing_for_type: dict[str, list[int]] = {}
        for ws in ProviderWorkspace.objects.filter(user__email__endswith='@tourista.rw').order_by('id'):
            listing_for_type.setdefault(ws.service_type, []).append(ws.linked_listing_id)
        counters: dict[str, int] = {}

        created = 0
        for b in payload['bookings']:
            if Booking.objects.filter(pk=b['id']).exists():
                continue
            p = b['payment']
            g = b['guestInfo']
            created_at = _parse_dt(b['createdAt']) + shift_dt
            service_id = str(b['serviceId'])
            options = listing_for_type.get(b['serviceType'])
            if options:
                index = counters.get(b['serviceType'], 0)
                counters[b['serviceType']] = index + 1
                listing_id = options[index % len(options)]
                _, _, option = service_id.partition(':')
                service_id = f'{listing_id}:{option}' if option else str(listing_id)
            Booking.objects.create(
                id=b['id'],
                reference=b['reference'],
                service_type=b['serviceType'],
                service_id=service_id,
                service_name=b['serviceName'],
                location=b.get('location', ''),
                image=b.get('image') or '',
                check_in=date.fromisoformat(b['checkIn'][:10]) + shift,
                check_out=date.fromisoformat(b['checkOut'][:10]) + shift,
                time_slot=b.get('timeSlot') or '',
                guests=b['guests'],
                unit_price=Decimal(str(b['unitPrice'])),
                guest_full_name=g['fullName'],
                guest_email=g['email'].lower(),
                guest_phone=g.get('phone', ''),
                special_requests=g.get('specialRequests') or '',
                payment_type=p['type'],
                payment_method=p['method'],
                payment_status=p['status'],
                total_amount=Decimal(str(p['totalAmount'])),
                amount_paid=Decimal(str(p['amountPaid'])),
                amount_due=Decimal(str(p['amountDue'])),
                deposit_percent=p.get('depositPercent', 30),
                paid_at=(_parse_dt(p.get('paidAt')) + shift_dt) if p.get('paidAt') else None,
                payment_reference=p.get('reference', ''),
                status=b['status'],
                fulfillment=b.get('fulfillment'),
                checked_in_at=(_parse_dt(b.get('checkedInAt')) + shift_dt) if b.get('checkedInAt') else None,
                checked_out_at=(_parse_dt(b.get('checkedOutAt')) + shift_dt) if b.get('checkedOutAt') else None,
                notes=b.get('notes') or '',
                created_at=created_at,
                updated_at=(_parse_dt(b.get('updatedAt')) + shift_dt) if b.get('updatedAt') else created_at,
            )
            created += 1
        self.stdout.write(f'Demo bookings created: {created} (shifted {shift.days} days).')
