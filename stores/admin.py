# apps/stores/admin.py
"""Django Admin для stores."""

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum

from .models import Region, City, Store, StoreSelection, StoreInventory


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    """Admin для областей."""

    list_display = ['id','name', 'stores_count', 'created_at']

    list_filter = ['created_at']

    search_fields = ['name']

    readonly_fields = ['created_at', 'updated_at', 'stores_count_display']

    fieldsets = [
        ('Основное', {
            'fields': ['name']
        }),
        ('Статистика', {
            'fields': ['stores_count_display'],
            'classes': ['collapse']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]

    def stores_count(self, obj):
        """Количество магазинов."""
        return obj.stores.count()

    stores_count.short_description = 'Магазинов'

    def stores_count_display(self, obj):
        """Количество магазинов (детально)."""
        total = obj.stores.count()
        active = obj.stores.filter(is_active=True).count()
        return format_html(
            'Всего: <strong>{}</strong> | Активных: <strong>{}</strong>',
            total, active
        )

    stores_count_display.short_description = 'Статистика магазинов'


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    """Admin для городов."""

    list_display = ['id','name', 'region', 'stores_count', 'created_at']

    list_filter = ['region', 'created_at']

    search_fields = ['name', 'region__name']

    readonly_fields = ['created_at', 'updated_at', 'stores_count_display']

    autocomplete_fields = ['region']

    fieldsets = [
        ('Основное', {
            'fields': ['name', 'region']
        }),
        ('Статистика', {
            'fields': ['stores_count_display'],
            'classes': ['collapse']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]

    def stores_count(self, obj):
        """Количество магазинов."""
        return obj.stores.count()

    stores_count.short_description = 'Магазинов'

    def stores_count_display(self, obj):
        """Количество магазинов (детально)."""
        total = obj.stores.count()
        active = obj.stores.filter(is_active=True).count()
        return format_html(
            'Всего: <strong>{}</strong> | Активных: <strong>{}</strong>',
            total, active
        )

    stores_count_display.short_description = 'Статистика магазинов'


class StoreInventoryInline(admin.TabularInline):
    """Инлайн для инвентаря."""
    model = StoreInventory
    extra = 0
    fields = ['id','product', 'quantity', 'total_price_display', 'last_updated']
    readonly_fields = ['total_price_display', 'last_updated']

    def total_price_display(self, obj):
        """Общая стоимость."""
        if obj.id:
            # ИСПРАВЛЕНО
            price_formatted = f'{obj.total_price:.2f}'
            return format_html('{} сом', price_formatted)
        return '-'

    total_price_display.short_description = 'Сумма'


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    """Admin для магазинов."""

    list_display = [
        'id',
        'name',
        'owner_name',
        'inn',
        'city',
        'approval_status_display',
        'is_active',
        'total_debt_display',
        'users_count',
        'created_at'
    ]

    list_filter = [
        'approval_status',
        'is_active',
        'city__region',
        'city',
        'created_at'
    ]

    search_fields = [
        'name',
        'owner_name',
        'inn',
        'phone',
        'address'
    ]

    readonly_fields = [
        'created_at',
        'updated_at',
        'total_debt_display',
        'inventory_summary',
        'users_count_display'
    ]

    autocomplete_fields = ['region', 'city']

    inlines = [StoreInventoryInline]

    fieldsets = [
        ('Основное', {
            'fields': [
                'name',
                'owner_name',
                'phone',
                'inn'
            ]
        }),
        ('Адрес', {
            'fields': ['region', 'city', 'address']
        }),
        ('Статус', {
            'fields': ['approval_status', 'is_active']
        }),
        ('Финансы', {
            'fields': ['debt', 'total_paid', 'total_debt_display'],
            'classes': ['collapse']
        }),
        ('Инвентарь', {
            'fields': ['inventory_summary'],
            'classes': ['collapse']
        }),
        ('Пользователи', {
            'fields': ['users_count_display'],
            'classes': ['collapse']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]

    def approval_status_display(self, obj):
        """Статус одобрения с цветом."""
        colors = {
            'pending': 'orange',
            'approved': 'green',
            'rejected': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.approval_status, 'gray'),
            obj.get_approval_status_display()
        )

    approval_status_display.short_description = 'Статус одобрения'

    def total_debt_display(self, obj):
        """Общий долг."""
        color = 'red' if obj.debt > 0 else 'green'
        debt_formatted = f'{obj.debt:.2f}'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} сом</span>',
            color, debt_formatted
        )

    total_debt_display.short_description = 'Долг'

    def inventory_summary(self, obj):
        """Сводка по инвентарю."""
        from django.db.models import Count, Sum

        stats = obj.inventory.aggregate(
            total_items=Count('id'),
            total_qty=Sum('quantity')
        )

        # ИСПРАВЛЕНО
        total_qty = stats['total_qty'] or 0
        qty_formatted = f'{total_qty:.2f}'

        return format_html(
            'Позиций: <strong>{}</strong> | Товаров: <strong>{}</strong>',
            stats['total_items'] or 0,
            qty_formatted
        )

    inventory_summary.short_description = 'Инвентарь'

    def users_count(self, obj):
        """Количество пользователей."""
        return obj.selections.filter(is_current=True).count()

    users_count.short_description = 'Пользователей'

    def users_count_display(self, obj):
        """Количество пользователей (детально)."""
        active = obj.selections.filter(is_current=True).count()
        total = obj.selections.count()

        return format_html(
            'Сейчас: <strong>{}</strong> | Всего было: <strong>{}</strong>',
            active, total
        )

    users_count_display.short_description = 'Пользователи'


@admin.register(StoreSelection)
class StoreSelectionAdmin(admin.ModelAdmin):
    """Admin для выбора магазинов."""

    list_display = [
        'user',
        'store',
        'is_current',
        'selected_at',
        'deselected_at'
    ]

    list_filter = [
        'is_current',
        'selected_at',
        'store__city__region'
    ]

    search_fields = [
        'user__email',
        'user__phone',
        'store__name',
        'store__inn'
    ]

    readonly_fields = ['selected_at', 'deselected_at']

    autocomplete_fields = ['user', 'store']

    fieldsets = [
        ('Основное', {
            'fields': ['user', 'store']
        }),
        ('Статус', {
            'fields': ['is_current']
        }),
        ('Временные метки', {
            'fields': ['selected_at', 'deselected_at']
        })
    ]


@admin.register(StoreInventory)
class StoreInventoryAdmin(admin.ModelAdmin):
    """Admin для инвентаря магазинов."""

    list_display = [
        'store',
        'product',
        'quantity',
        'total_price_display',
        'last_updated',
        'created_at'
    ]

    list_filter = [
        'store__city__region',
        'store',
        'created_at',
        'last_updated'
    ]

    search_fields = [
        'store__name',
        'store__inn',
        'product__name'
    ]

    readonly_fields = [
        'total_price_display',
        'created_at',
        'last_updated'
    ]

    autocomplete_fields = ['store', 'product']

    fieldsets = [
        ('Основное', {
            'fields': [
                'store',
                'product'
            ]
        }),
        ('Количество', {
            'fields': [
                'quantity',
                'total_price_display'
            ]
        }),
        ('Временные метки', {
            'fields': ['created_at', 'last_updated']
        })
    ]

    def total_price_display(self, obj):
        """Общая стоимость."""
        # ИСПРАВЛЕНО
        price_formatted = f'{obj.total_price:.2f}'
        return format_html('{} сом', price_formatted)