from django.contrib import admin

from .models import Facility, Listing, ReferenceData, TripPlan


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ['name', 'service_type', 'listing_id', 'province', 'category', 'rating', 'is_published']
    list_filter = ['service_type', 'is_published', 'province']
    search_fields = ['name', 'location', 'description']
    list_editable = ['is_published']


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ['name', 'service_type', 'listing_id', 'facility_id', 'kind', 'price', 'inventory', 'stock']
    list_filter = ['service_type', 'kind']
    search_fields = ['name', 'facility_id']
    list_editable = ['price', 'stock']


@admin.register(TripPlan)
class TripPlanAdmin(admin.ModelAdmin):
    list_display = ['user', 'created_at']
    raw_id_fields = ['user']


@admin.register(ReferenceData)
class ReferenceDataAdmin(admin.ModelAdmin):
    list_display = ['key', 'updated_at']
