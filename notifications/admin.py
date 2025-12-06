from django.contrib import admin
from .models import Notification, FCMToken


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'notification_type', 'title', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['user__email', 'user__phone', 'title', 'message']
    readonly_fields = ['created_at', 'read_at']
    ordering = ['-created_at']


@admin.register(FCMToken)
class FCMTokenAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'device_type', 'is_active', 'created_at']
    list_filter = ['device_type', 'is_active']
    search_fields = ['user__email', 'user__phone', 'token']
    readonly_fields = ['created_at', 'updated_at']
