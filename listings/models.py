from django.db import models

from core.constants import ServiceType

# Columns stored on the model; every other key of a listing lives in `data`.
CORE_FIELDS = ('name', 'location', 'province', 'image', 'rating', 'reviews', 'category', 'description')


class Listing(models.Model):
    """A public company/place page (hotel, park, restaurant, shop, ...).

    The frontend types differ per category (`Hotel`, `Park`, `SpaCenter`, ...), so
    common, filterable fields are real columns and the category-specific rest
    (rooms, treatments, highlights, ...) is kept verbatim in `data`.
    """

    service_type = models.CharField(max_length=32, choices=ServiceType.choices, db_index=True)
    listing_id = models.PositiveIntegerField(help_text='Public id used in frontend URLs, e.g. /hotels/3')
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    province = models.CharField(max_length=100, blank=True, db_index=True)
    image = models.CharField(max_length=500, blank=True)
    rating = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    reviews = models.PositiveIntegerField(default=0)
    category = models.CharField(max_length=100, blank=True, db_index=True)
    description = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    # Rating/review count from the original catalog; guest reviews are added on top.
    base_rating = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    base_reviews = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['service_type', 'listing_id']
        constraints = [
            models.UniqueConstraint(fields=['service_type', 'listing_id'], name='unique_listing_per_type'),
        ]

    def __str__(self):
        return f'[{self.service_type}] {self.name}'

    @classmethod
    def split_payload(cls, payload: dict) -> tuple[dict, dict]:
        """Split a frontend-shaped dict into (column values, extra JSON data)."""
        columns = {key: payload[key] for key in CORE_FIELDS if key in payload}
        extra = {key: value for key, value in payload.items() if key not in CORE_FIELDS and key != 'id'}
        return columns, extra

    def to_frontend(self) -> dict:
        return {
            **self.data,
            'id': self.listing_id,
            'name': self.name,
            'location': self.location,
            'province': self.province,
            'image': self.image,
            'rating': float(self.rating),
            'reviews': self.reviews,
            'category': self.category,
            'description': self.description,
        }


class Facility(models.Model):
    """A bookable unit on a public listing page: hotel room/service, park activity,
    shop product, spa treatment, ... Prices are in USD and are what bookings charge."""

    class Kind(models.TextChoices):
        ROOM = 'room', 'Room'
        SERVICE = 'service', 'Service'
        PRODUCT = 'product', 'Product'
        TREATMENT = 'treatment', 'Treatment'
        FACILITY = 'facility', 'Facility'

    service_type = models.CharField(max_length=32, choices=ServiceType.choices)
    listing_id = models.PositiveIntegerField()
    facility_id = models.CharField(max_length=120)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.FACILITY)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                help_text='USD. Empty = use the listing base price.')
    price_label = models.CharField(max_length=60, blank=True)
    image = models.CharField(max_length=500, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True, help_text='Max guests per booking/slot')
    inventory = models.PositiveIntegerField(null=True, blank=True, help_text='Rooms/vehicles of this type')
    stock = models.IntegerField(null=True, blank=True, help_text='Products only; empty = unlimited')

    class Meta:
        verbose_name_plural = 'facilities'
        ordering = ['service_type', 'listing_id', 'facility_id']
        constraints = [
            models.UniqueConstraint(
                fields=['service_type', 'listing_id', 'facility_id'], name='unique_facility_per_listing'
            ),
        ]

    def __str__(self):
        return f'[{self.service_type} {self.listing_id}] {self.name}'


class ReferenceData(models.Model):
    """Small named JSON blobs the UI needs (spa treatment catalog, shop categories)."""

    key = models.SlugField(max_length=64, unique=True)
    data = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'reference data'

    def __str__(self):
        return self.key


class TripPlan(models.Model):
    """A generated itinerary saved for a signed-in traveller."""

    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='trip_plans')
    request = models.JSONField(default=dict)
    plan = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
