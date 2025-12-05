# apps/orders/admin.py
"""Django Admin для orders."""

from django.contrib import admin
from .models import (
    StoreOrder,
    StoreOrderItem,
    PartnerOrder,
    PartnerOrderItem,
    DebtPayment,
    DefectiveProduct,
    OrderHistory,
)


class StoreOrderItemInline(admin.TabularInline):
    model = StoreOrderItem
    extra = 0
    readonly_fields = ['total']


@admin.register(StoreOrder)
class StoreOrderAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'store', 'partner', 'status',
        'total_amount', 'debt_amount', 'prepayment_amount',
        'created_at'
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['store__name', 'store__inn']
    readonly_fields = [
        'debt_amount', 'paid_amount', 'outstanding_debt',
        'reviewed_by', 'reviewed_at',
        'confirmed_by', 'confirmed_at',
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
                'debt_amount', 'paid_amount', 'outstanding_debt'
            ]
        }),
        ('Workflow', {
            'fields': [
                'reviewed_by', 'reviewed_at',
                'confirmed_by', 'confirmed_at'
            ]
        }),
        ('Системное', {
            'fields': ['idempotency_key', 'created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]


@admin.register(DebtPayment)
class DebtPaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'order', 'amount', 'paid_by', 'received_by', 'created_at']
    list_filter = ['created_at']
    search_fields = ['order__id', 'order__store__name']
    readonly_fields = ['created_at']


@admin.register(DefectiveProduct)
class DefectiveProductAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'order', 'product', 'quantity',
        'total_amount', 'status', 'created_at'
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['order__id', 'product__name']
    readonly_fields = ['total_amount', 'created_at', 'updated_at']


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'order_type', 'order_id',
        'old_status', 'new_status',
        'changed_by', 'created_at'
    ]
    list_filter = ['order_type', 'created_at']
    search_fields = ['order_id', 'comment']
    readonly_fields = ['created_at']