from django.contrib import admin
from .models import Chat, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ['sender', 'content', 'is_read', 'created_at']
    can_delete = False


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ['id', 'get_participants', 'updated_at']
    filter_horizontal = ['participants']
    inlines = [MessageInline]

    def get_participants(self, obj):
        return ', '.join(str(u) for u in obj.participants.all())
    get_participants.short_description = 'Участники'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'chat', 'sender', 'content_preview', 'is_read', 'created_at']
    list_filter = ['is_read', 'created_at']
    search_fields = ['content', 'sender__phone']
    readonly_fields = ['created_at']

    def content_preview(self, obj):
        return obj.content[:60]
    content_preview.short_description = 'Текст'
