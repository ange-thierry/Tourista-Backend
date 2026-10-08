import io
import re
import shutil
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import User
from bookings.models import Booking, Notification
from core.constants import UserRole
from listings.models import Facility, Listing
from providers.models import AvailabilityRule, CatalogItem

PASSWORD = 'Secret#123'


def day(offset: int) -> str:
    return (timezone.localdate() + timedelta(days=offset)).isoformat()


def hotel_payload(**overrides):
    """Book provider catalog room u2-h1 (Deluxe Twin, $180/night) at hotel 1."""
    payload = {
        'serviceType': 'hotel',
        'serviceId': '1:u2-h1',
        'serviceName': 'Anything the client says',
        'checkIn': day(10),
        'checkOut': day(12),
        'guests': 2,
        'unitPrice': 1,
        'totalAmount': 1,
        'guestInfo': {'fullName': 'Ada Guest', 'email': 'ada@example.com', 'phone': '+250 700 000 000'},
        'paymentType': 'partial',
        'paymentMethod': 'mobile_money',
    }
    payload.update(overrides)
    return payload


def make_user(email, role=UserRole.TOURIST, **extra):
    extra.setdefault('email_verified', True)
    return User.objects.create_user(email=email, password=PASSWORD, name=email.split('@')[0].title(), role=role,
                                    **extra)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class SeededTestCase(TestCase):
    """Seeds listings, facilities and demo provider accounts once per class."""

    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', '--no-bookings', verbosity=0, stdout=StringIO())
        cls.hotel = User.objects.get(email='hotel@tourista.rw')
        cls.spa = User.objects.get(email='spa@tourista.rw')
        cls.shop = User.objects.get(email='shop@tourista.rw')
        cls.admin = User.objects.get(email='admin@tourista.rw')
        cls.tourist = make_user('ada@example.com')

    def book(self, client=None, expect=201, **overrides):
        client = client or client_for(self.tourist)
        res = client.post('/api/bookings/', hotel_payload(**overrides), format='json')
        self.assertEqual(res.status_code, expect, res.data)
        return res.data


# --- auth ------------------------------------------------------------------------


class AuthTests(SeededTestCase):
    def test_register_sets_refresh_cookie_only(self):
        client = APIClient()
        res = client.post('/api/auth/register/', {
            'email': 'New@Example.com', 'password': PASSWORD, 'name': 'New Person', 'role': 'hotel_owner',
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertNotIn('refresh', res.data)
        self.assertIn('access', res.data)
        cookie = res.cookies[settings.REFRESH_COOKIE_NAME]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['path'], '/api/auth/')
        self.assertFalse(res.data['user']['emailVerified'])

        refreshed = client.post('/api/auth/refresh/')
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn('access', refreshed.data)
        # The old refresh token was rotated out and can't be reused.
        reuse = APIClient().post('/api/auth/refresh/', {'refresh': cookie.value}, format='json')
        self.assertEqual(reuse.status_code, 401)

        client.post('/api/auth/logout/')
        self.assertEqual(client.post('/api/auth/refresh/').status_code, 401)

    def test_cannot_self_register_as_admin(self):
        res = APIClient().post('/api/auth/register/', {
            'email': 'x@example.com', 'password': PASSWORD, 'name': 'X', 'role': 'admin',
        }, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('message', res.data)

    def test_wrong_password(self):
        res = APIClient().post('/api/auth/login/', {'email': 'ada@example.com', 'password': 'nope'}, format='json')
        self.assertEqual(res.status_code, 400)

    def _link_params(self, message):
        match = re.search(r'uid=([^&\s]+)&token=([^\s]+)', message.body)
        return {'uid': match.group(1), 'token': match.group(2)}

    def test_email_verification_claims_guest_bookings(self):
        # Someone books as a guest with this email; it must not appear in the account
        # until the owner proves the email is theirs.
        self.book(client=APIClient(), guestInfo={'fullName': 'Bo', 'email': 'bo@example.com'})
        mail.outbox.clear()
        res = APIClient().post('/api/auth/register/', {
            'email': 'bo@example.com', 'password': PASSWORD, 'name': 'Bo', 'role': 'tourist',
        }, format='json')
        user = User.objects.get(email='bo@example.com')
        self.assertEqual(client_for(user).get('/api/bookings/').data, [])
        self.assertEqual(len(mail.outbox), 1)

        verify = APIClient().post('/api/auth/verify-email/', self._link_params(mail.outbox[0]), format='json')
        self.assertEqual(verify.status_code, 200, verify.data)
        self.assertEqual(verify.data['claimedBookings'], 1)
        self.assertEqual(len(client_for(user).get('/api/bookings/').data), 1)
        # Links are single-use.
        again = APIClient().post('/api/auth/verify-email/', self._link_params(mail.outbox[0]), format='json')
        self.assertEqual(again.status_code, 400)

    def test_password_reset(self):
        self.assertEqual(APIClient().post('/api/auth/password-reset/', {'email': 'nobody@example.com'}).status_code, 204)
        self.assertEqual(len(mail.outbox), 0)
        APIClient().post('/api/auth/password-reset/', {'email': 'ada@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        params = {**self._link_params(mail.outbox[0]), 'password': 'Brand-new#456'}
        self.assertEqual(APIClient().post('/api/auth/password-reset/confirm/', params, format='json').status_code, 200)
        login = APIClient().post('/api/auth/login/', {'email': 'ada@example.com', 'password': 'Brand-new#456'},
                                 format='json')
        self.assertEqual(login.status_code, 200)
        self.assertEqual(APIClient().post('/api/auth/password-reset/confirm/', params, format='json').status_code, 400)


# --- pricing & availability ------------------------------------------------------------


class PricingTests(SeededTestCase):
    def test_server_sets_price_and_name(self):
        data = self.book()
        self.assertEqual(data['unitPrice'], 180)
        self.assertEqual(data['payment']['totalAmount'], 360)  # 2 nights, not the client's $1
        self.assertEqual(data['payment']['amountPaid'], 108)
        self.assertEqual(data['payment']['amountDue'], 252)
        self.assertIn('Deluxe Twin Room', data['serviceName'])
        self.assertEqual(data['listingId'], 1)

    def test_public_facility_price(self):
        data = self.book(serviceId='1:1-room-deluxe')
        price = float(Facility.objects.get(service_type='hotel', listing_id=1, facility_id='1-room-deluxe').price)
        self.assertEqual(data['payment']['totalAmount'], price * 2)

    def test_per_guest_pricing_with_slot(self):
        data = self.book(serviceType='spa', serviceId='1:aromatherapy', checkIn=day(3), checkOut=day(3),
                         timeSlot='10:00 – 11:00', guests=2)
        self.assertEqual(data['payment']['totalAmount'], 130)
        self.assertEqual(data['fulfillment'], 'not_started')

    def test_unknown_option_rejected(self):
        self.book(serviceId='1:does-not-exist', expect=400)
        self.book(serviceType='shop', serviceId='1', checkIn=day(2), checkOut=day(2), expect=400)

    def test_quote(self):
        res = APIClient().post('/api/bookings/quote/', {
            'serviceType': 'hotel', 'serviceId': '1:u2-h1', 'checkIn': day(5), 'checkOut': day(8), 'guests': 2,
        }, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['totalAmount'], 540)
        self.assertEqual(res.data['nights'], 3)
        self.assertTrue(res.data['available'])


class AvailabilityTests(SeededTestCase):
    def test_overnight_inventory(self):
        CatalogItem.objects.filter(pk='u2-h1').update(total_count=1)
        self.book()
        res = client_for(self.tourist).post('/api/bookings/', hotel_payload(checkIn=day(11), checkOut=day(13)),
                                            format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('Not available', res.data['message'])
        # Non-overlapping stay (check-out day is free) is fine.
        self.book(checkIn=day(12), checkOut=day(14))

    def test_slot_capacity(self):
        spa = dict(serviceType='spa', serviceId='1:aromatherapy', checkIn=day(4), checkOut=day(4),
                   timeSlot='10:00 – 11:00', guests=2)
        self.book(**spa)
        res = client_for(self.tourist).post('/api/bookings/', hotel_payload(**{**spa, 'guests': 1}), format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('fully booked', res.data['message'])
        self.book(**{**spa, 'timeSlot': '11:00'})
        # Missing slot for an appointment
        self.book(**{**spa, 'timeSlot': ''}, expect=400)

    def test_blocked_dates_and_closed_slots(self):
        ws = self.spa.workspaces.get()
        AvailabilityRule.objects.filter(workspace=ws).update(blocked_dates=[day(6)], closed_time_slots=['09:00'])
        common = dict(serviceType='spa', serviceId='1:aromatherapy', guests=1)
        self.book(**common, checkIn=day(6), checkOut=day(6), timeSlot='10:00', expect=400)
        self.book(**common, checkIn=day(7), checkOut=day(7), timeSlot='09:00', expect=400)
        self.book(**common, checkIn=day(7), checkOut=day(7), timeSlot='10:00')

    def test_past_dates(self):
        self.book(checkIn=day(-1), checkOut=day(1), expect=400)

    def test_stock(self):
        product = Facility.objects.get(service_type='shop', listing_id=1, facility_id='1-product-1-1')
        order = dict(serviceType='shop', serviceId='1:1-product-1-1', checkIn=day(2), checkOut=day(2), timeSlot='')
        self.book(**order, guests=product.stock + 1, expect=400)
        data = self.book(**order, guests=3)
        product.refresh_from_db()
        self.assertEqual(product.stock, 6)
        client_for(self.tourist).post(f'/api/bookings/{data["id"]}/status/', {'status': 'cancelled'})
        product.refresh_from_db()
        self.assertEqual(product.stock, 9)

    def test_calendar_endpoint(self):
        CatalogItem.objects.filter(pk='u2-h1').update(total_count=1)
        self.book()
        res = APIClient().get('/api/availability/', {'service_type': 'hotel', 'service_id': '1:u2-h1',
                                                    'from': day(9), 'to': day(13)})
        self.assertEqual(res.data['days'][day(9)], 'free')
        self.assertEqual(res.data['days'][day(10)], 'full')
        self.assertEqual(res.data['days'][day(12)], 'free')
        slots = APIClient().get('/api/availability/', {'service_type': 'spa', 'service_id': '1:aromatherapy',
                                                      'date': day(3)}).data['slots']
        self.assertEqual(slots[0]['time'], '08:00')
        self.assertEqual(slots[0]['status'], 'free')


# --- lifecycle ----------------------------------------------------------------------


class LifecycleTests(SeededTestCase):
    def test_guest_cannot_checkout_unpaid(self):
        data = self.book(checkIn=day(0), checkOut=day(2))
        tourist = client_for(self.tourist)
        tourist.post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_in'})
        res = tourist.post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_out'})
        self.assertEqual(res.status_code, 400)
        self.assertIn('Pay the remaining balance', res.data['message'])
        paid = tourist.post(f'/api/bookings/{data["id"]}/pay-balance/', {'method': 'card'}).data
        self.assertEqual(paid['payment']['amountDue'], 0)
        res = tourist.post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_out'})
        self.assertEqual(res.status_code, 200)

    def test_guest_cannot_check_in_early(self):
        data = self.book()
        res = client_for(self.tourist).post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_in'})
        self.assertEqual(res.status_code, 400)

    def test_provider_checkout_collects_balance(self):
        data = self.book(checkIn=day(0), checkOut=day(2))
        hotel = client_for(self.hotel)
        hotel.post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_in'})
        res = hotel.post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_out'})
        self.assertEqual(res.data['payment']['status'], 'paid')
        self.assertEqual(res.data['payment']['amountDue'], 0)

    def test_transitions_enforced(self):
        data = self.book()
        tourist = client_for(self.tourist)
        cancelled = tourist.post(f'/api/bookings/{data["id"]}/status/', {'status': 'cancelled'}).data
        self.assertEqual(cancelled['payment']['status'], 'refunded')
        self.assertEqual(cancelled['payment']['amountRefunded'], 108)
        self.assertEqual(cancelled['payment']['amountPaid'], 0)
        res = client_for(self.hotel).post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_in'})
        self.assertEqual(res.status_code, 400)
        self.assertIn('cannot become', res.data['message'])

    def test_guest_cannot_confirm_or_complete(self):
        data = self.book()
        tourist = client_for(self.tourist)
        self.assertEqual(tourist.post(f'/api/bookings/{data["id"]}/status/', {'status': 'completed'}).status_code, 403)

    def test_fulfillment_forward_only(self):
        data = self.book(serviceType='spa', serviceId='1:aromatherapy', checkIn=day(3), checkOut=day(3),
                         timeSlot='10:00', guests=1)
        spa = client_for(self.spa)
        url = f'/api/bookings/{data["id"]}/fulfillment/'
        self.assertEqual(spa.post(url, {'fulfillment': 'delivered'}).status_code, 400)  # shop step
        self.assertEqual(spa.post(url, {'fulfillment': 'in_service'}).data['status'], 'checked_in')
        self.assertEqual(spa.post(url, {'fulfillment': 'not_started'}).status_code, 400)
        done = spa.post(url, {'fulfillment': 'fulfilled'}).data
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(done['payment']['amountDue'], 0)

    def test_archive_and_restore(self):
        data = self.book()
        hotel = client_for(self.hotel)
        self.assertEqual(client_for(self.tourist).delete(f'/api/bookings/{data["id"]}/').status_code, 403)
        self.assertEqual(hotel.delete(f'/api/bookings/{data["id"]}/').status_code, 204)
        self.assertTrue(Booking.objects.get(pk=data['id']).is_archived)
        self.assertEqual(hotel.get('/api/bookings/').data, [])
        self.assertEqual(len(hotel.get('/api/bookings/', {'archived': 1}).data), 1)
        hotel.post(f'/api/bookings/{data["id"]}/restore/')
        self.assertEqual(len(hotel.get('/api/bookings/').data), 1)


class ScopeTests(SeededTestCase):
    def test_provider_sees_only_own_listing(self):
        mine = self.book()
        other_hotel = make_user('other-hotel@example.com', UserRole.HOTEL_OWNER)
        other = client_for(other_hotel)
        other_ws = other.get('/api/provider/workspace/').data
        self.assertNotEqual(other_ws['profile']['linkedListingId'], 1)
        self.assertEqual(other.get('/api/bookings/').data, [])
        self.assertEqual(other.post(f'/api/bookings/{mine["id"]}/status/', {'status': 'cancelled'}).status_code, 403)
        self.assertEqual(len(client_for(self.hotel).get('/api/bookings/').data), 1)
        self.assertEqual(client_for(self.spa).get('/api/bookings/').data, [])

    def test_typed_email_does_not_reach_other_accounts(self):
        victim = make_user('victim@example.com')
        self.book(client=APIClient(), guestInfo={'fullName': 'Spam', 'email': 'victim@example.com'})
        self.assertFalse(Notification.objects.filter(user=victim).exists())
        self.assertEqual(client_for(victim).get('/api/bookings/').data, [])

    def test_notifications_and_provider_alert(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.book()
        self.assertEqual(Notification.objects.filter(user=self.tourist).count(), 2)
        self.assertEqual(Notification.objects.filter(user=self.hotel).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.spa).count(), 0)
        self.assertEqual(len(mail.outbox), 2)  # guest confirmation + provider alert

    def test_pagination(self):
        for offset in (20, 24, 28):
            self.book(checkIn=day(offset), checkOut=day(offset + 1))
        page = client_for(self.tourist).get('/api/bookings/', {'page': 1, 'page_size': 2}).data
        self.assertEqual(page['count'], 3)
        self.assertEqual(len(page['results']), 2)
        self.assertTrue(page['hasMore'])

    def test_stats_and_export(self):
        self.book()
        stats = client_for(self.hotel).get('/api/bookings/stats/').data
        self.assertEqual(stats['bookings'], 1)
        self.assertEqual(stats['revenue'], 108)
        res = client_for(self.hotel).get('/api/bookings/export.csv')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Reference', res.content.decode())
        self.assertEqual(client_for(self.tourist).get('/api/bookings/export.csv').status_code, 403)


# --- reviews, messaging, staff, uploads ----------------------------------------------------------


class ReviewTests(SeededTestCase):
    def test_review_flow(self):
        data = self.book(checkIn=day(0), checkOut=day(1))
        tourist = client_for(self.tourist)
        body = {'bookingId': data['id'], 'rating': 5, 'comment': 'Lovely stay'}
        self.assertEqual(tourist.post('/api/reviews/', body, format='json').status_code, 400)  # not finished

        hotel = client_for(self.hotel)
        hotel.post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_in'})
        hotel.post(f'/api/bookings/{data["id"]}/status/', {'status': 'checked_out'})
        listing = Listing.objects.get(service_type='hotel', listing_id=1)
        before = listing.reviews
        review = tourist.post('/api/reviews/', body, format='json')
        self.assertEqual(review.status_code, 201, review.data)
        self.assertEqual(tourist.post('/api/reviews/', body, format='json').status_code, 400)  # duplicate
        listing.refresh_from_db()
        self.assertEqual(listing.reviews, before + 1)

        public = APIClient().get('/api/reviews/', {'service_type': 'hotel', 'listing_id': 1}).data
        self.assertEqual(public['summary']['guestReviews'], 1)
        inbox = hotel.get('/api/reviews/provider/').data
        self.assertEqual(inbox['summary']['unanswered'], 1)
        reply = hotel.post(f'/api/reviews/{review.data["id"]}/reply/', {'reply': 'Thank you!'}, format='json')
        self.assertEqual(reply.data['reply'], 'Thank you!')
        other = client_for(self.spa).post(f'/api/reviews/{review.data["id"]}/reply/', {'reply': 'x'}, format='json')
        self.assertEqual(other.status_code, 403)


class MessagingTests(SeededTestCase):
    def test_conversation(self):
        data = self.book()
        tourist, hotel = client_for(self.tourist), client_for(self.hotel)
        convo = tourist.post('/api/conversations/', {'bookingId': data['id'], 'message': 'Early check-in?'},
                             format='json')
        self.assertEqual(convo.status_code, 201, convo.data)
        inbox = hotel.get('/api/conversations/').data
        self.assertEqual(inbox[0]['unread'], 1)
        self.assertEqual(inbox[0]['bookingReference'], data['reference'])
        thread = hotel.get(f'/api/conversations/{convo.data["id"]}/messages/').data
        self.assertEqual(thread['messages'][0]['body'], 'Early check-in?')
        hotel.post(f'/api/conversations/{convo.data["id"]}/messages/', {'body': 'Yes, from noon.'}, format='json')
        self.assertEqual(tourist.get('/api/conversations/').data[0]['unread'], 1)
        self.assertEqual(client_for(self.spa).get(f'/api/conversations/{convo.data["id"]}/messages/').status_code,
                         403)


class ProviderTests(SeededTestCase):
    def test_workspace_seeded(self):
        ws = client_for(self.hotel).get('/api/provider/workspace/').data
        self.assertEqual(ws['serviceType'], 'hotel')
        self.assertEqual(ws['profile']['companyName'], 'Kigali Serena Hotel')
        self.assertEqual(len(ws['catalog']), 4)

    def test_tourist_has_no_workspace(self):
        self.assertEqual(client_for(self.tourist).get('/api/provider/workspace/').status_code, 403)

    def test_catalog_upsert_and_delete(self):
        hotel = client_for(self.hotel)
        item = {'name': 'Garden Room', 'price': 99, 'status': 'active', 'scheduleMode': 'overnight'}
        ws = hotel.put('/api/provider/catalog/item_test_1/', item, format='json').data
        self.assertIn('Garden Room', [c['name'] for c in ws['catalog']])
        ws = hotel.delete('/api/provider/catalog/item_test_1/').data
        self.assertNotIn('item_test_1', [c['id'] for c in ws['catalog']])

    def test_cannot_overwrite_other_providers_item(self):
        res = client_for(self.hotel).put('/api/provider/catalog/u11-sp1/', {'name': 'x', 'price': 1}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_staff_crud(self):
        hotel = client_for(self.hotel)
        member = hotel.post('/api/provider/staff/', {'name': 'Jean', 'position': 'Front desk'}, format='json')
        self.assertEqual(member.status_code, 201, member.data)
        updated = hotel.patch(f'/api/provider/staff/{member.data["id"]}/', {'status': 'on_leave'}, format='json')
        self.assertEqual(updated.data['status'], 'on_leave')
        self.assertEqual(client_for(self.spa).delete(f'/api/provider/staff/{member.data["id"]}/').status_code, 404)
        self.assertEqual(hotel.delete(f'/api/provider/staff/{member.data["id"]}/').status_code, 204)


class UploadTests(SeededTestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_image_upload(self):
        buffer = io.BytesIO()
        Image.new('RGB', (40, 30), 'green').save(buffer, format='PNG')
        buffer.seek(0)
        buffer.name = 'room.png'
        res = client_for(self.hotel).post('/api/uploads/', {'file': buffer}, format='multipart')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data['url'].endswith('.png'))

        fake = io.BytesIO(b'<script>alert(1)</script>')
        fake.name = 'evil.png'
        res = client_for(self.hotel).post('/api/uploads/', {'file': fake}, format='multipart')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(APIClient().post('/api/uploads/', {}).status_code, 401)


# --- admin, discovery, listings ------------------------------------------------------------------


class AdminApiTests(SeededTestCase):
    def test_overview_and_users(self):
        self.book()
        admin = client_for(self.admin)
        overview = admin.get('/api/admin/overview/').data
        self.assertEqual(overview['bookings']['bookings'], 1)
        self.assertGreaterEqual(overview['users']['total'], 13)
        self.assertEqual(client_for(self.tourist).get('/api/admin/overview/').status_code, 403)
        users = admin.get('/api/admin/users/', {'search': 'ada'}).data
        self.assertEqual(users[0]['email'], 'ada@example.com')
        res = admin.patch(f'/api/admin/users/{self.tourist.pk}/', {'isActive': False}, format='json')
        self.assertFalse(res.data['isActive'])

    def test_inquiries(self):
        with self.captureOnCommitCallbacks(execute=True):
            APIClient().post('/api/contact/', {'name': 'A', 'email': 'a@b.co', 'subject': 'Hi', 'message': 'Hello'},
                             format='json')
        self.assertEqual(len(mail.outbox), 1)  # staff alert
        items = client_for(self.admin).get('/api/admin/inquiries/').data
        res = client_for(self.admin).patch(f'/api/admin/inquiries/contact/{items[0]["id"]}/', {'handled': True},
                                           format='json')
        self.assertTrue(res.data['handled'])


class DiscoveryTests(SeededTestCase):
    def test_search(self):
        res = APIClient().get('/api/search/', {'q': 'gorilla'}).data
        self.assertGreater(res['count'], 0)
        self.assertIn('url', res['results'][0])
        parks = APIClient().get('/api/search/', {'type': 'park'}).data
        self.assertTrue(all(r['type'] == 'park' for r in parks['results']))

    def test_trip_plan(self):
        res = APIClient().post('/api/trip-plans/', {
            'destination': 'Volcanoes National Park', 'duration': '3 days', 'budget': '$3000', 'travelers': '2',
            'interests': 'wildlife',
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(len(res.data['dailyItinerary']), 3)
        self.assertEqual(res.data['destination'], 'Volcanoes National Park')
        self.assertTrue(res.data['suggestions'])
        saved = client_for(self.tourist).post('/api/trip-plans/', {'destination': 'Kigali'}, format='json')
        self.assertIn('id', saved.data)
        self.assertEqual(len(client_for(self.tourist).get('/api/trip-plans/').data), 1)


class ListingTests(SeededTestCase):
    def test_hotel_shape(self):
        hotels = APIClient().get('/api/listings/hotel/').data
        self.assertEqual(len(hotels), 20)
        for key in ('id', 'name', 'pricePerNight', 'rooms', 'services', 'amenities'):
            self.assertIn(key, hotels[0])

    def test_grouped_and_detail(self):
        grouped = APIClient().get('/api/listings/').data
        self.assertEqual(len(grouped), 9)
        self.assertEqual(APIClient().get('/api/listings/park/1/').data['id'], 1)
        self.assertEqual(APIClient().get('/api/listings/nope/').status_code, 404)

    def test_demo_request(self):
        res = APIClient().post('/api/demo-requests/', {
            'fullName': 'A', 'email': 'a@b.co', 'preferredDate': '2030-01-01', 'preferredTime': '09:00 AM',
        }, format='json')
        self.assertEqual(res.status_code, 201)


class TripPlannerMatchTests(SeededTestCase):
    def test_destination_name_prefers_attractions(self):
        res = APIClient().post('/api/trip-plans/', {'destination': 'Lake Kivu', 'duration': '2 days'}, format='json')
        self.assertEqual(res.data['destination'], 'Lake Kivu')
        self.assertEqual(res.data['region'], 'western')
