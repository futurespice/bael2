# apps/orders/admin.py

from django.contrib import admin

from .models import (
    OrderHistory,
    OrderReturn,
    OrderReturnItem,
    PartnerOrder,
    PartnerOrderItem,
    StoreOrder,
    StoreOrderItem,
)


class PartnerOrderItemInline(admin.TabularInline):
    model = PartnerOrderItem
    extra = 0
    readonly_fields = ("total",)


@admin.register(PartnerOrder)
class PartnerOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "partner",
        "status",
        "total_amount",
        "created_at",
    )
    list_filter = ("status", "partner", "created_at")
    search_fields = ("id", "partner__phone", "partner__email")
    readonly_fields = ("total_amount", "created_at", "updated_at")
    inlines = [PartnerOrderItemInline]


class StoreOrderItemInline(admin.TabularInline):
    model = StoreOrderItem
    extra = 0
    readonly_fields = ("total",)


@admin.register(StoreOrder)
class StoreOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "store",
        "partner",
        "status",
        "total_amount",
        "debt_amount",
        "paid_amount",
        "created_at",
    )
    list_filter = ("status", "store", "partner", "created_at")
    search_fields = ("id", "store__name", "partner__phone", "partner__email")
    readonly_fields = ("total_amount", "created_at", "updated_at")
    inlines = [StoreOrderItemInline]


class OrderReturnItemInline(admin.TabularInline):
    model = OrderReturnItem
    extra = 0
    readonly_fields = ("total",)


@admin.register(OrderReturn)
class OrderReturnAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "store",
        "partner",
        "order",
        "status",
        "total_amount",
        "created_at",
    )
    list_filter = ("status", "store", "partner", "created_at")
    search_fields = ("id", "store__name", "partner__phone", "partner__email")
    readonly_fields = ("total_amount", "created_at", "updated_at")
    inlines = [OrderReturnItemInline]


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order_type",
        "order_id",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    )
    list_filter = ("order_type", "old_status", "new_status", "created_at")
    search_fields = ("order_id", "changed_by__phone", "changed_by__email")
    readonly_fields = ("order_type", "order_id", "old_status", "new_status", "created_at")
