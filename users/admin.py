from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, PasswordResetRequest


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['phone', 'email', 'name', 'second_name', 'role', 'approval_status', 'is_active', 'created_at']
    list_filter = ['role', 'approval_status', 'is_active', 'created_at']
    search_fields = ['phone', 'email', 'name', 'second_name']
    ordering = ['-created_at']

    fieldsets = (
        (None, {'fields': ('phone', 'password')}),
        ('Личная информация', {'fields': ('name', 'second_name', 'email', 'avatar')}),
        ('Роль и права', {'fields': ('role', 'approval_status', 'is_active', 'is_staff', 'is_superuser')}),
        ('Группы', {'fields': ('groups', 'user_permissions')}),
        ('Даты', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )

    readonly_fields = ['created_at', 'updated_at']

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone', 'email', 'name', 'second_name', 'password1', 'password2', 'role'),
        }),
    )

    # Переопределяем actions для одобрения партнёров
    actions = ['approve_users', 'reject_users', 'block_users', 'unblock_users']

    def approve_users(self, request, queryset):
        """Массовое одобрение пользователей"""
        updated = queryset.update(approval_status='approved')
        self.message_user(request, f'Одобрено {updated} пользователей')

    approve_users.short_description = 'Одобрить выбранных пользователей'

    def reject_users(self, request, queryset):
        """Массовое отклонение пользователей"""
        updated = queryset.update(approval_status='rejected')
        self.message_user(request, f'Отклонено {updated} пользователей')

    reject_users.short_description = 'Отклонить выбранных пользователей'

    def block_users(self, request, queryset):
        """Массовая блокировка пользователей"""
        updated = queryset.exclude(role='admin').update(is_active=False)
        self.message_user(request, f'Заблокировано {updated} пользователей')

    block_users.short_description = 'Заблокировать выбранных пользователей'

    def unblock_users(self, request, queryset):
        """Массовая разблокировка пользователей"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'Разблокировано {updated} пользователей')

    unblock_users.short_description = 'Разблокировать выбранных пользователей'


@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'code', 'created_at', 'expires_at', 'is_used']
    list_filter = ['is_used', 'created_at']
    search_fields = ['user__email', 'user__phone', 'code']
    readonly_fields = ['created_at']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
