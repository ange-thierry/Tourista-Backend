from django.conf import settings
from django.db import models

from core.constants import ServiceType, UserRole
from core.utils import make_id


class ScheduleMode(models.TextChoices):
    OVERNIGHT = 'overnight', 'Overnight'
    DAY_VISIT = 'day_visit', 'Day visit'
    ORDER = 'order', 'Order'


class CatalogItemStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    DRAFT = 'draft', 'Draft'
    PAUSED = 'paused', 'Paused'


def default_time_slots() -> list[str]:
    return [f'{hour:02d}:00' for hour in range(8, 20)]


class ProviderWorkspace(models.Model):
    """A provider's company page settings (frontend `ProviderWorkspace`)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workspaces')
    role = models.CharField(max_length=32, choices=UserRole.choices)
    service_type = models.CharField(max_length=32, choices=ServiceType.choices, db_index=True)

    # Company profile
    company_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    province = models.CharField(max_length=100, blank=True)
    hours = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    amenities = models.JSONField(default=list, blank=True)
    image = models.CharField(max_length=500, blank=True)
    linked_listing_id = models.PositiveIntegerField(
        default=1, help_text='Public listing (same service type) this workspace manages'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'role'], name='one_workspace_per_user_role'),
        ]

    def __str__(self):
        return f'{self.company_name} ({self.service_type})'


class CatalogItem(models.Model):
    """A room, tour, treatment, product, ... (frontend `ProviderCatalogItem`)."""

    id = models.CharField(primary_key=True, max_length=64)
    workspace = models.ForeignKey(ProviderWorkspace, on_delete=models.CASCADE, related_name='catalog')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price_label = models.CharField(max_length=60, blank=True)
    image = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=CatalogItemStatus.choices, default=CatalogItemStatus.DRAFT)
    schedule_mode = models.CharField(max_length=12, choices=ScheduleMode.choices, default=ScheduleMode.DAY_VISIT)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    stock = models.IntegerField(null=True, blank=True)
    available_count = models.IntegerField(null=True, blank=True)
    total_count = models.IntegerField(null=True, blank=True)
    amenities = models.JSONField(default=list, blank=True)
    beds = models.CharField(max_length=100, blank=True)
    size_sqm = models.PositiveIntegerField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'name']

    def __str__(self):
        return self.name

    @staticmethod
    def new_id() -> str:
        return make_id('item')


class AvailabilityRule(models.Model):
    """Blocked dates / open time slots for one catalog item or the whole company (`item_id='all'`)."""

    id = models.CharField(primary_key=True, max_length=64)
    workspace = models.ForeignKey(ProviderWorkspace, on_delete=models.CASCADE, related_name='availability')
    item_id = models.CharField(max_length=64, default='all')
    blocked_dates = models.JSONField(default=list, blank=True)
    limited_dates = models.JSONField(default=list, blank=True)
    open_time_slots = models.JSONField(default=default_time_slots, blank=True)
    closed_time_slots = models.JSONField(default=list, blank=True)
    capacity_per_day = models.PositiveIntegerField(default=4)
    notes = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position']

    def __str__(self):
        return f'{self.workspace} · {self.item_id}'

    @staticmethod
    def new_id() -> str:
        return make_id('av')


class StaffMember(models.Model):
    """Team members of a provider company (front desk, guides, therapists, drivers, ...)."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        ON_LEAVE = 'on_leave', 'On leave'
        INACTIVE = 'inactive', 'Inactive'

    workspace = models.ForeignKey(ProviderWorkspace, on_delete=models.CASCADE, related_name='staff')
    name = models.CharField(max_length=150)
    position = models.CharField(max_length=100)
    department = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    shift = models.CharField(max_length=60, blank=True, help_text='e.g. "Morning 06:00–14:00"')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    hired_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['department', 'name']

    def __str__(self):
        return f'{self.name} ({self.position})'
