import re

from rest_framework import serializers

from core.utils import iso, money

from .models import AvailabilityRule, CatalogItem, CatalogItemStatus, ProviderWorkspace, ScheduleMode, StaffMember

TIME_RE = re.compile(r'^\d{2}:\d{2}$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def catalog_item_to_frontend(item: CatalogItem) -> dict:
    data = {
        'id': item.id,
        'name': item.name,
        'description': item.description,
        'category': item.category,
        'price': money(item.price),
        'priceLabel': item.price_label,
        'image': item.image,
        'status': item.status,
        'scheduleMode': item.schedule_mode,
        'durationMinutes': item.duration_minutes,
        'capacity': item.capacity,
        'stock': item.stock,
        'availableCount': item.available_count,
        'totalCount': item.total_count,
        'amenities': item.amenities or [],
        'beds': item.beds or None,
        'sizeSqm': item.size_sqm,
    }
    return {key: value for key, value in data.items() if value is not None}


def availability_to_frontend(rule: AvailabilityRule) -> dict:
    return {
        'id': rule.id,
        'itemId': rule.item_id,
        'blockedDates': rule.blocked_dates,
        'limitedDates': rule.limited_dates,
        'openTimeSlots': rule.open_time_slots,
        'closedTimeSlots': rule.closed_time_slots,
        'capacityPerDay': rule.capacity_per_day,
        'notes': rule.notes,
    }


def workspace_to_frontend(ws: ProviderWorkspace, *, public: bool = False) -> dict:
    catalog = ws.catalog.all()
    if public:
        catalog = [item for item in catalog if item.status == CatalogItemStatus.ACTIVE]
    return {
        'userId': str(ws.user_id),
        'role': ws.role,
        'serviceType': ws.service_type,
        'profile': {
            'companyName': ws.company_name,
            'description': ws.description,
            'location': ws.location,
            'province': ws.province,
            'hours': ws.hours,
            'phone': ws.phone,
            'amenities': ws.amenities or [],
            'image': ws.image,
            'linkedListingId': ws.linked_listing_id,
        },
        'catalog': [catalog_item_to_frontend(item) for item in catalog],
        'availability': [availability_to_frontend(rule) for rule in ws.availability.all()],
        'updatedAt': iso(ws.updated_at),
    }


class ProfileSerializer(serializers.Serializer):
    """Partial update of the company profile (camelCase keys, all optional)."""

    companyName = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    location = serializers.CharField(max_length=200, allow_blank=True, required=False)
    province = serializers.CharField(max_length=100, allow_blank=True, required=False)
    hours = serializers.CharField(max_length=100, allow_blank=True, required=False)
    phone = serializers.CharField(max_length=40, allow_blank=True, required=False)
    amenities = serializers.ListField(child=serializers.CharField(max_length=100), required=False)
    image = serializers.CharField(max_length=500, allow_blank=True, required=False)
    linkedListingId = serializers.IntegerField(min_value=1, required=False)

    FIELD_MAP = {
        'companyName': 'company_name',
        'linkedListingId': 'linked_listing_id',
    }

    def model_values(self) -> dict:
        return {self.FIELD_MAP.get(key, key): value for key, value in self.validated_data.items()}


class CatalogItemSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, required=False, default='')
    category = serializers.CharField(max_length=100, allow_blank=True, required=False, default='')
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    priceLabel = serializers.CharField(max_length=60, allow_blank=True, required=False, default='')
    image = serializers.CharField(max_length=500, allow_blank=True, required=False, default='')
    status = serializers.ChoiceField(choices=CatalogItemStatus.choices, default=CatalogItemStatus.DRAFT)
    scheduleMode = serializers.ChoiceField(choices=ScheduleMode.choices, default=ScheduleMode.DAY_VISIT)
    durationMinutes = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    capacity = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    stock = serializers.IntegerField(required=False, allow_null=True)
    availableCount = serializers.IntegerField(required=False, allow_null=True)
    totalCount = serializers.IntegerField(required=False, allow_null=True)
    amenities = serializers.ListField(child=serializers.CharField(max_length=100), required=False, default=list)
    beds = serializers.CharField(max_length=100, allow_blank=True, required=False, allow_null=True)
    sizeSqm = serializers.IntegerField(min_value=0, required=False, allow_null=True)

    def model_values(self) -> dict:
        v = self.validated_data
        return {
            'name': v['name'],
            'description': v.get('description', ''),
            'category': v.get('category', ''),
            'price': v['price'],
            'price_label': v.get('priceLabel', ''),
            'image': v.get('image', ''),
            'status': v['status'],
            'schedule_mode': v['scheduleMode'],
            'duration_minutes': v.get('durationMinutes'),
            'capacity': v.get('capacity'),
            'stock': v.get('stock'),
            'available_count': v.get('availableCount'),
            'total_count': v.get('totalCount'),
            'amenities': v.get('amenities') or [],
            'beds': v.get('beds') or '',
            'size_sqm': v.get('sizeSqm'),
        }


def _validated_list(values, pattern: re.Pattern, label: str) -> list[str]:
    for value in values:
        if not pattern.match(value):
            raise serializers.ValidationError(f'Invalid {label}: "{value}".')
    return sorted(set(values))


class AvailabilityRuleSerializer(serializers.Serializer):
    itemId = serializers.CharField(max_length=64, default='all')
    blockedDates = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    limitedDates = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    openTimeSlots = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    closedTimeSlots = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    capacityPerDay = serializers.IntegerField(min_value=0, default=4)
    notes = serializers.CharField(allow_blank=True, required=False, default='')

    def validate_blockedDates(self, value):
        return _validated_list(value, DATE_RE, 'date')

    def validate_limitedDates(self, value):
        return _validated_list(value, DATE_RE, 'date')

    def validate_openTimeSlots(self, value):
        return _validated_list(value, TIME_RE, 'time slot')

    def validate_closedTimeSlots(self, value):
        return _validated_list(value, TIME_RE, 'time slot')

    def model_values(self) -> dict:
        v = self.validated_data
        return {
            'item_id': v['itemId'],
            'blocked_dates': v['blockedDates'],
            'limited_dates': v['limitedDates'],
            'open_time_slots': v['openTimeSlots'],
            'closed_time_slots': v['closedTimeSlots'],
            'capacity_per_day': v['capacityPerDay'],
            'notes': v.get('notes', ''),
        }


class StaffSerializer(serializers.ModelSerializer):
    """camelCase fields for the staff screens."""

    hiredOn = serializers.DateField(source='hired_on', required=False, allow_null=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = StaffMember
        fields = ['id', 'name', 'position', 'department', 'email', 'phone', 'shift', 'status', 'hiredOn',
                  'notes', 'createdAt']
