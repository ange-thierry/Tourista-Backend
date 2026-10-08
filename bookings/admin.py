from django.contrib import admin

from .models import Booking, Notification


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        'reference', 'service_name', 'service_type', 'guest_full_name', 'check_in',
        'status', 'payment_status', 'total_amount', 'amount_due', 'created_at',
    ]
    list_filter = ['service_type', 'status', 'payment_status', 'fulfillment', 'is_archived']
    search_fields = ['reference', 'service_name', 'guest_full_name', 'guest_email']
    date_hierarchy = 'check_in'
    raw_id_fields = ['user', 'archived_by']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'type', 'read', 'created_at']
    list_filter = ['type', 'read']
    search_fields = ['title', 'message', 'user__email']
    raw_id_fields = ['user', 'booking']
