from django.contrib import admin

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    raw_id_fields = ['sender']


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['subject', 'guest', 'workspace', 'updated_at']
    search_fields = ['subject', 'guest__email', 'workspace__company_name']
    raw_id_fields = ['guest', 'workspace', 'booking']
    inlines = [MessageInline]
