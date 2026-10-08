from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['user', 'service_type', 'listing_id', 'rating', 'is_published', 'created_at']
    list_filter = ['service_type', 'rating', 'is_published']
    search_fields = ['comment', 'title', 'user__email']
    raw_id_fields = ['user', 'booking']
