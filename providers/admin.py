from django.contrib import admin

from .models import AvailabilityRule, CatalogItem, ProviderWorkspace, StaffMember


class CatalogItemInline(admin.TabularInline):
    model = CatalogItem
    extra = 0
    fields = ['id', 'name', 'category', 'price', 'price_label', 'status', 'schedule_mode', 'stock']


class AvailabilityRuleInline(admin.TabularInline):
    model = AvailabilityRule
    extra = 0
    fields = ['id', 'item_id', 'capacity_per_day', 'blocked_dates', 'notes']


class StaffInline(admin.TabularInline):
    model = StaffMember
    extra = 0
    fields = ['name', 'position', 'department', 'email', 'shift', 'status']


@admin.register(ProviderWorkspace)
class ProviderWorkspaceAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'user', 'role', 'service_type', 'linked_listing_id', 'updated_at']
    list_filter = ['role', 'service_type']
    search_fields = ['company_name', 'user__email']
    raw_id_fields = ['user']
    inlines = [CatalogItemInline, AvailabilityRuleInline, StaffInline]
