# apps/orders/admin.py - ОЧИЩЕННАЯ ВЕРСИЯ v2.1
"""
Django Admin для orders.

ИЗМЕНЕНИЯ v2.1:
- УДАЛЁН PartnerOrderAdmin (модель удалена)
"""

from django.contrib import admin
from .models import (
    StoreOrder,
    StoreOrderItem,
    DebtPayment,
    DefectiveProduct,
    OrderHistory,
)


class StoreOrderItemInline(admin.TabularInline):
    """Inline для позиций заказа."""
    model = StoreOrderItem
    extra = 0
    readonly_fields = ['total']
    fields = ['product', 'quantity', 'price', 'total', 'is_bonus']


@admin.register(StoreOrder)
class StoreOrderAdmin(admin.ModelAdmin):
    """Admin для заказов магазинов."""

    list_display = [
        'id', 'store', 'partner', 'status',
        'total_amount', 'debt_amount', 'prepayment_amount',
        'outstanding_debt_display',
        'created_at'
    ]

    list_filter = ['status', 'created_at', 'partner']

    search_fields = ['store__name', 'store__inn', 'id']

    readonly_fields = [
        'total_amount',
        'debt_amount', 'paid_amount', 'outstanding_debt_display',
        'reviewed_by', 'reviewed_at',
        'confirmed_by', 'confirmed_at',
        'created_by',
        'created_at', 'updated_at'
    ]

    inlines = [StoreOrderItemInline]

    fieldsets = [
        ('Основное', {
            'fields': ['store', 'partner', 'status', 'created_by']
        }),
        ('Финансы', {
            'fields': [
                'total_amount', 'prepayment_amount',
                'debt_amount', 'paid_amount', 'outstanding_debt_display'
            ]
        }),
        ('Workflow', {
            'fields': [
                ('reviewed_by', 'reviewed_at'),
                ('confirmed_by', 'confirmed_at'),
                'reject_reason'
            ]
        }),
        ('Системное', {
            'fields': ['idempotency_key', 'created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    def outstanding_debt_display(self, obj):
        """Отображение непогашенного долга."""
        return f"{obj.outstanding_debt} сом"

    outstanding_debt_display.short_description = 'Непогашенный долг'

    actions = ['approve_orders', 'reject_orders']

    def approve_orders(self, request, queryset):
        """Массовое одобрение заказов."""
        from .models import StoreOrderStatus
        updated = queryset.filter(status=StoreOrderStatus.PENDING).update(
            status=StoreOrderStatus.IN_TRANSIT,
            reviewed_by=request.user
        )
        self.message_user(request, f'Одобрено {updated} заказов')

    approve_orders.short_description = 'Одобрить выбранные заказы'

    def reject_orders(self, request, queryset):
        """Массовое отклонение заказов."""
        from .models import StoreOrderStatus
        updated = queryset.filter(status=StoreOrderStatus.PENDING).update(
            status=StoreOrderStatus.REJECTED,
            reviewed_by=request.user
        )
        self.message_user(request, f'Отклонено {updated} заказов')

    reject_orders.short_description = 'Отклонить выбранные заказы'


@admin.register(DebtPayment)
class DebtPaymentAdmin(admin.ModelAdmin):
    """Admin для погашений долга."""

    list_display = ['id', 'order', 'amount', 'paid_by', 'received_by', 'created_at']

    list_filter = ['created_at']

    search_fields = ['order__id', 'order__store__name', 'comment']

    readonly_fields = ['created_at']

    fieldsets = [
        ('Основное', {
            'fields': ['order', 'amount', 'comment']
        }),
        ('Участники', {
            'fields': ['paid_by', 'received_by']
        }),
        ('Системное', {
            'fields': ['created_at'],
            'classes': ['collapse']
        }),
    ]


@admin.register(DefectiveProduct)
class DefectiveProductAdmin(admin.ModelAdmin):
    """Admin для бракованных товаров."""

    list_display = [
        'id', 'order', 'product', 'quantity',
        'total_amount', 'status', 'created_at'
    ]

    list_filter = ['status', 'created_at']

    search_fields = ['order__id', 'product__name', 'reason']

    readonly_fields = ['total_amount', 'created_at', 'updated_at']

    fieldsets = [
        ('Основное', {
            'fields': ['order', 'product', 'quantity', 'price', 'total_amount']
        }),
        ('Статус', {
            'fields': ['status', 'reason']
        }),
        ('Участники', {
            'fields': ['reported_by', 'reviewed_by']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    actions = ['approve_defects', 'reject_defects']

    def approve_defects(self, request, queryset):
        """Массовое подтверждение брака."""
        from .models import DefectiveProduct
        updated = queryset.filter(
            status=DefectiveProduct.DefectStatus.PENDING
        ).update(
            status=DefectiveProduct.DefectStatus.APPROVED,
            reviewed_by=request.user
        )
        self.message_user(request, f'Подтверждено {updated} записей о браке')

    approve_defects.short_description = 'Подтвердить выбранный брак'

    def reject_defects(self, request, queryset):
        """Массовое отклонение брака."""
        from .models import DefectiveProduct
        updated = queryset.filter(
            status=DefectiveProduct.DefectStatus.PENDING
        ).update(
            status=DefectiveProduct.DefectStatus.REJECTED,
            reviewed_by=request.user
        )
        self.message_user(request, f'Отклонено {updated} записей о браке')

    reject_defects.short_description = 'Отклонить выбранный брак'


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    """Admin для истории заказов."""

    list_display = [
        'id', 'order_type', 'order_id',
        'old_status', 'new_status',
        'changed_by', 'created_at'
    ]

    list_filter = ['order_type', 'created_at']

    search_fields = ['order_id', 'comment']

    readonly_fields = ['created_at']

    fieldsets = [
        ('Заказ', {
            'fields': ['order_type', 'order_id', 'product']
        }),
        ('Изменение', {
            'fields': ['old_status', 'new_status', 'comment']
        }),
        ('Системное', {
            'fields': ['changed_by', 'created_at'],
            'classes': ['collapse']
        }),
    ]

# =============================================================================
# УДАЛЁННЫЕ ADMIN-КЛАССЫ (v2.1)
# =============================================================================
#
# PartnerOrderAdmin - УДАЛЁН (модель PartnerOrder удалена)
#
# =============================================================================