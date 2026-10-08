"""Cross-category search and the rule-based trip planner, both built on real listings."""

import math
import re
from datetime import date

from django.db.models import Q
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.engine import _base_price
from core.constants import ServiceType

from .models import Facility, Listing, TripPlan

PUBLIC_PATHS = {
    ServiceType.HOTEL: '/hotels',
    ServiceType.DESTINATION: '/destinations',
    ServiceType.PARK: '/parks',
    ServiceType.RESTAURANT: '/restaurants',
    ServiceType.TRANSPORT: '/transport',
    ServiceType.ARTISAN: '/artisans',
    ServiceType.SHOP: '/shops',
    ServiceType.SPA: '/massage-sauna',
    ServiceType.HISTORY_CULTURE: '/history-culture',
}

PRICE_LABELS = {
    ServiceType.HOTEL: 'per night',
    ServiceType.TRANSPORT: 'per day',
    ServiceType.SHOP: 'per item',
}

# Keywords that place a listing (or a free-text destination) in one of Rwanda's regions.
REGIONS = {
    'northern': ['northern', 'musanze', 'volcano', 'ruhengeri', 'burera', 'ruhondo'],
    'western': ['western', 'kivu', 'gisenyi', 'rubavu', 'karongi', 'kibuye', 'rusizi', 'gishwati', 'nyamasheke'],
    'southern': ['southern', 'huye', 'butare', 'nyanza', 'nyungwe', 'nyamagabe', 'muhanga'],
    'eastern': ['eastern', 'akagera', 'nyakarambi', 'kayonza', 'rwamagana', 'kirehe', 'bugesera'],
    'kigali': ['kigali', 'gisozi', 'kimihurura', 'nyarugenge', 'kacyiru', 'remera'],
}

# Interest keywords → (listing types, words to look for in a listing).
INTERESTS = {
    'wildlife': ([ServiceType.PARK, ServiceType.DESTINATION], ['gorilla', 'wildlife', 'safari', 'chimp', 'monkey', 'bird']),
    'nature': ([ServiceType.PARK, ServiceType.DESTINATION], ['forest', 'lake', 'hike', 'hiking', 'canopy', 'nature', 'waterfall']),
    'culture': ([ServiceType.HISTORY_CULTURE, ServiceType.ARTISAN], ['culture', 'museum', 'history', 'heritage', 'memorial', 'art']),
    'food': ([ServiceType.RESTAURANT], ['food', 'cuisine', 'dining', 'coffee']),
    'relax': ([ServiceType.SPA], ['spa', 'massage', 'wellness', 'relax', 'sauna']),
    'shopping': ([ServiceType.SHOP, ServiceType.ARTISAN], ['shopping', 'craft', 'market', 'souvenir']),
    'adventure': ([ServiceType.PARK, ServiceType.DESTINATION], ['adventure', 'trek', 'volcano', 'kayak', 'boat']),
}


def region_of_text(text: str) -> str | None:
    text = text.lower()
    for region, words in REGIONS.items():
        if any(word in text for word in words):
            return region
    return None


def region_of(listing: Listing) -> str | None:
    return region_of_text(f'{listing.province} {listing.location}') or region_of_text(listing.name)


def listing_price(listing: Listing):
    """(USD price, label) for display, or (None, '') when it varies per item."""
    if listing.service_type == ServiceType.SHOP:
        prices = Facility.objects.filter(
            service_type=listing.service_type, listing_id=listing.listing_id, price__isnull=False
        ).values_list('price', flat=True)
        cheapest = min(prices, default=None)
        return (float(cheapest), 'from / item') if cheapest is not None else (None, '')
    price = _base_price(listing)
    if price is None:
        return None, ''
    return float(price), PRICE_LABELS.get(listing.service_type, 'per person')


def _first(data: dict, *keys):
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None


def to_search_result(listing: Listing) -> dict:
    data = listing.data
    price, label = listing_price(listing)
    return {
        'id': f'{listing.service_type}-{listing.listing_id}',
        'listingId': listing.listing_id,
        'type': listing.service_type,
        'name': listing.name,
        'description': listing.description,
        'category': listing.category,
        'location': f'{listing.location}, {listing.province}' if listing.province else listing.location,
        'province': listing.province,
        'region': region_of(listing),
        'image': listing.image,
        'rating': float(listing.rating),
        'reviews': listing.reviews,
        'price': (f'Free' if price == 0 else f'${price:,.0f} {label}') if price is not None else None,
        'priceValue': price,
        'url': f'{PUBLIC_PATHS[listing.service_type]}/{listing.listing_id}',
        'details': {
            'amenities': _first(data, 'amenities', 'facilities', 'services', 'visitExperiences') or [],
            'highlights': _first(data, 'highlights', 'activities', 'specialties', 'learningHighlights', 'cuisine') or [],
            'contact': {'phone': _first(data, 'contact', 'phone'), 'website': data.get('website')},
            'availability': _first(data, 'hours', 'openingHours', 'availability', 'bestTimeToVisit'),
            'duration': data.get('duration'),
        },
    }


class SearchView(APIView):
    """`GET /api/search/?q=gorilla&type=park,destination&region=northern&min_price=&max_price=&sort=`"""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        params = request.query_params
        qs = Listing.objects.filter(is_published=True)
        if types := params.get('type', '').strip():
            if types != 'all':
                qs = qs.filter(service_type__in=types.split(','))
        terms = [t for t in re.split(r'\s+', params.get('q', '').strip()) if t]
        for term in terms:
            qs = qs.filter(
                Q(name__icontains=term)
                | Q(location__icontains=term)
                | Q(province__icontains=term)
                | Q(description__icontains=term)
                | Q(category__icontains=term)
            )
        results = [to_search_result(listing) for listing in qs]
        if region := params.get('region'):
            results = [r for r in results if r['region'] == region]
        try:
            min_price = float(params['min_price']) if params.get('min_price') else None
            max_price = float(params['max_price']) if params.get('max_price') else None
            min_rating = float(params.get('min_rating') or 0)
        except ValueError:
            min_price = max_price = None
            min_rating = 0
        if min_price is not None:
            results = [r for r in results if r['priceValue'] is not None and r['priceValue'] >= min_price]
        if max_price is not None:
            results = [r for r in results if r['priceValue'] is not None and r['priceValue'] <= max_price]
        results = [r for r in results if r['rating'] >= min_rating]

        sort = params.get('sort', 'relevance')
        if sort == 'rating':
            results.sort(key=lambda r: r['rating'], reverse=True)
        elif sort == 'price-low':
            results.sort(key=lambda r: (r['priceValue'] is None, r['priceValue'] or 0))
        elif sort == 'price-high':
            results.sort(key=lambda r: r['priceValue'] or 0, reverse=True)
        elif sort == 'name':
            results.sort(key=lambda r: r['name'])
        elif terms:
            # Relevance: name matches first, then rating.
            lowered = [t.lower() for t in terms]
            results.sort(key=lambda r: (-sum(t in r['name'].lower() for t in lowered), -r['rating']))
        return Response({'count': len(results), 'results': results[:200]})


# --- trip planner ---------------------------------------------------------------


class TripRequestSerializer(serializers.Serializer):
    destination = serializers.CharField(max_length=200, allow_blank=True, required=False, default='')
    startDate = serializers.DateField(required=False, allow_null=True)
    endDate = serializers.DateField(required=False, allow_null=True)
    duration = serializers.CharField(max_length=40, allow_blank=True, required=False, default='')
    budget = serializers.CharField(max_length=40, allow_blank=True, required=False, default='')
    travelers = serializers.CharField(max_length=10, allow_blank=True, required=False, default='1')
    interests = serializers.CharField(max_length=500, allow_blank=True, required=False, default='')
    accommodation = serializers.CharField(max_length=60, allow_blank=True, required=False, default='')
    travelStyle = serializers.CharField(max_length=60, allow_blank=True, required=False, default='')


def _number(text: str, default: float | None = None) -> float | None:
    match = re.search(r'\d[\d,]*(?:\.\d+)?', text or '')
    return float(match.group().replace(',', '')) if match else default


def _days(v: dict) -> int:
    start, end = v.get('startDate'), v.get('endDate')
    if start and end and end >= start:
        days = (end - start).days + 1
    else:
        text = (v.get('duration') or '').lower()
        days = int(_number(text, 3) or 3)
        if 'week' in text:
            days *= 7
    return min(max(days, 1), 14)


def _interest_keys(text: str, style: str) -> list[str]:
    text = f'{text} {style}'.lower()
    keys = [key for key, (_, words) in INTERESTS.items() if key in text or any(w in text for w in words)]
    return keys or ['wildlife', 'culture', 'nature']


def _score(listing: Listing, interest_keys: list[str], destination: str) -> float:
    haystack = f'{listing.name} {listing.category} {listing.description} {" ".join(map(str, listing.data.get("highlights", []) + listing.data.get("activities", [])))}'.lower()
    score = float(listing.rating)
    for key in interest_keys:
        types, words = INTERESTS[key]
        if listing.service_type in types:
            score += 0.5
        score += 0.3 * sum(word in haystack for word in words)
    if destination and destination.lower() in listing.name.lower():
        score += 5
    return score


def _money(amount: float) -> str:
    return f'${amount:,.0f}'


def build_trip_plan(v: dict) -> dict:
    destination = (v.get('destination') or '').strip()
    days = _days(v)
    nights = max(days - 1, 1)
    travelers = max(int(_number(v.get('travelers') or '1', 1) or 1), 1)
    rooms = math.ceil(travelers / 2)
    budget = _number(v.get('budget') or '')
    interest_keys = _interest_keys(v.get('interests', ''), v.get('travelStyle', ''))

    listings = list(Listing.objects.filter(is_published=True))
    # Prefer places to visit when the destination matches a name ("Lake Kivu" is the lake,
    # not "Lake Kivu Soap Cooperative").
    named_order = {ServiceType.DESTINATION: 0, ServiceType.PARK: 1, ServiceType.HISTORY_CULTURE: 2}
    named = min(
        (l for l in listings if destination and destination.lower() in l.name.lower()),
        key=lambda l: (named_order.get(l.service_type, 9), len(l.name)),
        default=None,
    )
    region = (region_of(named) if named else None) or region_of_text(destination)

    def in_region(items):
        local = [l for l in items if region and region_of(l) == region]
        return local or items

    attraction_types = {ServiceType.DESTINATION, ServiceType.PARK, ServiceType.HISTORY_CULTURE}
    for key in interest_keys:
        attraction_types.update(t for t in INTERESTS[key][0] if t not in (ServiceType.RESTAURANT, ServiceType.SHOP))
    attractions = in_region([l for l in listings if l.service_type in attraction_types])
    attractions.sort(key=lambda l: _score(l, interest_keys, destination), reverse=True)
    if named and named in attractions:
        attractions.remove(named)
        attractions.insert(0, named)
    picks = attractions[:days]

    hotels = in_region([l for l in listings if l.service_type == ServiceType.HOTEL])
    pref = f'{v.get("accommodation", "")} {v.get("travelStyle", "")}'.lower()
    nightly = lambda h: float(h.data.get('pricePerNight') or 0)  # noqa: E731
    if 'luxury' in pref:
        hotel = max(hotels, key=lambda h: (nightly(h), float(h.rating)), default=None)
    elif 'budget' in pref or 'backpack' in pref:
        hotel = min(hotels, key=nightly, default=None)
    else:
        cap = (budget * 0.4 / nights / rooms) if budget else None
        affordable = [h for h in hotels if cap is None or nightly(h) <= cap]
        hotel = max(affordable or hotels, key=lambda h: float(h.rating), default=None) if affordable else min(
            hotels, key=nightly, default=None)

    restaurants = sorted(in_region([l for l in listings if l.service_type == ServiceType.RESTAURANT]),
                         key=lambda l: float(l.rating), reverse=True)
    transports = [l for l in listings if l.service_type == ServiceType.TRANSPORT and _base_price(l)]
    transport = min(transports, key=lambda l: _base_price(l), default=None)

    accommodation_cost = nightly(hotel) * nights * rooms if hotel else 0
    activity_cost = sum(float(_base_price(a) or 0) * travelers for a in picks)
    meal_cost = (float(_base_price(restaurants[0]) or 15) if restaurants else 15) * travelers * days * 2
    transport_cost = float(_base_price(transport) or 0) * days if transport else 0
    total = accommodation_cost + activity_cost + meal_cost + transport_cost

    itinerary = []
    for index in range(days):
        attraction = picks[index] if index < len(picks) else None
        restaurant = restaurants[index % len(restaurants)] if restaurants else None
        activities = []
        if index == 0:
            activities.append(f'Arrive and check in at {hotel.name}' if hotel else 'Arrive in Rwanda and check in')
        if attraction:
            activities.append(f'Visit {attraction.name}')
            extra = attraction.data.get('highlights') or attraction.data.get('activities') or attraction.data.get(
                'visitExperiences') or []
            activities.extend(str(item) for item in extra[:2])
        else:
            activities.append('Free day: explore local markets and cafés')
        if restaurant:
            activities.append(f'Dinner at {restaurant.name}')
        if index == days - 1 and days > 1:
            activities.append('Check out and depart')
        tip = ''
        if attraction:
            tip = attraction.data.get('bestTimeToVisit') or attraction.data.get('duration') or ''
            tip = f'{attraction.name}: {tip}' if tip else attraction.description[:140]
        itinerary.append({'day': index + 1, 'activities': activities, 'recommendations': tip})

    highlights = [a.name for a in picks][:6]
    tips = []
    if any('gorilla' in f'{a.name} {a.description}'.lower() for a in picks):
        tips.append('Gorilla permits sell out: book them several months ahead.')
    tips += list({a.data['bestTimeToVisit'] for a in picks if a.data.get('bestTimeToVisit')})[:2]
    tips += [
        'Carry layers: evenings are cool in the hills and near the volcanoes.',
        'Mobile money and cards are widely accepted in towns; carry some cash for rural areas.',
        'All prices above are live Tourista prices in USD; book from each listing page.',
    ]
    breakdown = [
        {'category': 'Accommodation', 'amount': _money(accommodation_cost),
         'description': f'{hotel.name}, {nights} night{"s" if nights != 1 else ""} × {rooms} room{"s" if rooms != 1 else ""}' if hotel else 'No hotel found'},
        {'category': 'Activities', 'amount': _money(activity_cost),
         'description': f'Entry/experience fees for {travelers} traveler{"s" if travelers != 1 else ""}'},
        {'category': 'Food', 'amount': _money(meal_cost), 'description': 'About two restaurant meals per day'},
        {'category': 'Transport', 'amount': _money(transport_cost),
         'description': f'{transport.name} for {days} day{"s" if days != 1 else ""}' if transport else 'Local transport'},
    ]

    def suggestion(listing: Listing | None, role: str):
        if not listing:
            return None
        price, label = listing_price(listing)
        return {'role': role, 'type': listing.service_type, 'listingId': listing.listing_id, 'name': listing.name,
                'url': f'{PUBLIC_PATHS[listing.service_type]}/{listing.listing_id}', 'price': price, 'priceLabel': label}

    suggestions = [s for s in [suggestion(hotel, 'stay')] + [suggestion(a, 'visit') for a in picks]
                   + [suggestion(r, 'eat') for r in restaurants[:2]] + [suggestion(transport, 'transport')] if s]

    return {
        'destination': named.name if named else (destination or (region or 'Rwanda').title()),
        'region': region,
        'duration': f'{days} day{"s" if days != 1 else ""}',
        'days': days,
        'travelers': travelers,
        'budget': _money(budget) if budget else _money(total),
        'estimatedTotal': round(total, 2),
        'withinBudget': None if not budget else total <= budget,
        'highlights': highlights,
        'dailyItinerary': itinerary,
        'travelTips': tips,
        'budgetBreakdown': breakdown,
        'suggestions': suggestions,
        'generatedAt': date.today().isoformat(),
    }


class TripPlanView(APIView):
    """POST generates a plan (saved when signed in); GET lists your saved plans."""

    def get_permissions(self):
        return [permissions.AllowAny()] if self.request.method == 'POST' else [permissions.IsAuthenticated()]

    def get(self, request):
        plans = TripPlan.objects.filter(user=request.user)[:20]
        return Response([{'id': p.id, 'createdAt': p.created_at.isoformat(), **p.plan} for p in plans])

    def post(self, request):
        serializer = TripRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = build_trip_plan(serializer.validated_data)
        if request.user.is_authenticated:
            saved = TripPlan.objects.create(user=request.user, request=request.data, plan=plan)
            plan = {'id': saved.id, **plan}
        return Response(plan, status=status.HTTP_201_CREATED)
