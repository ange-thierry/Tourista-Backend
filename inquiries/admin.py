from django.contrib import admin

from .models import ContactMessage, DemoRequest


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'subject', 'handled', 'created_at']
    list_filter = ['handled']
    list_editable = ['handled']
    search_fields = ['name', 'email', 'subject', 'message']


@admin.register(DemoRequest)
class DemoRequestAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'stakeholder_type', 'preferred_date', 'preferred_time', 'handled']
    list_filter = ['handled', 'stakeholder_type']
    list_editable = ['handled']
    search_fields = ['full_name', 'email', 'company']
