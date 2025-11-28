# apps/stores/admin.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
from django.contrib import admin
from django.utils.html import format_html
from decimal import Decimal
from .models import (
    Region, City, Store, StoreSelection,
    StoreProductRequest, StoreRequest, StoreRequestItem,
    StoreInventory, PartnerInventory, ReturnRequest, ReturnRequestItem
)


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ['id','name']
    search_fields = ['name']


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ['id','name', 'region']
    list_filter = ['region']
    search_fields = ['name']


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'inn', 'owner_name', 'phone',
        'city', 'approval_status', 'debt', 'is_active'
    ]
    list_filter = ['approval_status', 'is_active', 'region', 'city']
    search_fields = ['name', 'inn', 'owner_name', 'phone']
    readonly_fields = ['debt', 'created_at', 'updated_at']

    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'inn', 'owner_name', 'phone')
        }),
        ('Местоположение', {
            'fields': ('region', 'city', 'address', 'latitude', 'longitude')
        }),
        ('Финансы', {
            'fields': ('debt',)
        }),
        ('Статус', {
            'fields': ('approval_status', 'is_active')
        }),
        ('Системная информация', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )

    def save_model(self, request, obj, form, change):
        obj.full_clean()  # Вызовет clean()
        super().save_model(request, obj, form, change)


@admin.register(StoreSelection)
class StoreSelectionAdmin(admin.ModelAdmin):
    list_display = ['user', 'store', 'selected_at']
    list_filter = ['selected_at']
    search_fields = ['user__email', 'store__name']


@admin.register(StoreProductRequest)
class StoreProductRequestAdmin(admin.ModelAdmin):
    list_display = ['store', 'product', 'quantity', 'created_at']
    list_filter = ['created_at']
    search_fields = ['store__name', 'product__name']


class StoreRequestItemInline(admin.TabularInline):
    model = StoreRequestItem
    extra = 1

    # ИСПРАВЛЕНИЕ #17: Безопасное отображение в админке
    readonly_fields = ['calculated_total']
    fields = ['product', 'quantity', 'price', 'calculated_total', 'is_cancelled']

    def calculated_total(self, obj):
        """
        ИСПРАВЛЕНИЕ #17: Защита от NoneType при отображении
        """
        if obj.price is not None and obj.quantity is not None:
            total = obj.price * obj.quantity
            return f"{total} сом"
        return "Не рассчитано"

    calculated_total.short_description = 'Итого'


@admin.register(StoreRequest)
class StoreRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'store', 'created_by', 'total_amount', 'created_at']
    list_filter = ['created_at']
    search_fields = ['store__name']
    readonly_fields = ['total_amount', 'created_at']
    inlines = [StoreRequestItemInline]

    def save_model(self, request, obj, form, change):
        """
        ИСПРАВЛЕНИЕ #17: Безопасное сохранение с расчётом total_amount
        """
        super().save_model(request, obj, form, change)

        # Пересчитываем total_amount после сохранения всех items
        if obj.pk:
            total = Decimal('0')
            for item in obj.items.all():
                if item.price is not None and item.quantity is not None and not item.is_cancelled:
                    total += item.price * item.quantity

            obj.total_amount = total
            obj.save(update_fields=['total_amount'])


@admin.register(StoreInventory)
class StoreInventoryAdmin(admin.ModelAdmin):
    list_display = ['store', 'product', 'quantity', 'last_updated']
    list_filter = ['store', 'last_updated']
    search_fields = ['store__name', 'product__name']


@admin.register(PartnerInventory)
class PartnerInventoryAdmin(admin.ModelAdmin):
    list_display = ['partner', 'product', 'quantity', 'last_updated']
    list_filter = ['partner', 'last_updated']
    search_fields = ['partner__name', 'product__name']


class ReturnRequestItemInline(admin.TabularInline):
    model = ReturnRequestItem
    extra = 1

    # ИСПРАВЛЕНИЕ #18: Безопасное отображение в админке
    readonly_fields = ['calculated_total']
    fields = ['product', 'quantity', 'price', 'calculated_total']

    def calculated_total(self, obj):
        """
        ИСПРАВЛЕНИЕ #18: Защита от NoneType при отображении
        """
        if obj.price is not None and obj.quantity is not None:
            total = obj.price * obj.quantity
            return f"{total} сом"
        return "Не рассчитано"

    calculated_total.short_description = 'Итого'


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'partner', 'status', 'total_amount', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['partner__name', 'partner__email']
    readonly_fields = ['total_amount', 'created_at']
    inlines = [ReturnRequestItemInline]

    def save_model(self, request, obj, form, change):
        """
        ИСПРАВЛЕНИЕ #18: Безопасное сохранение с расчётом total_amount
        """
        # ИСПРАВЛЕНИЕ #17/#18: Устанавливаем default значения если None
        if not change:  # При создании
            obj.total_amount = Decimal('0')

        super().save_model(request, obj, form, change)

        # Пересчитываем total_amount после сохранения всех items
        if obj.pk:
            total = Decimal('0')
            for item in obj.items.all():
                if item.price is not None and item.quantity is not None:
                    total += item.price * item.quantity

            obj.total_amount = total
            obj.save(update_fields=['total_amount'])


@admin.register(StoreRequestItem)
class StoreRequestItemAdmin(admin.ModelAdmin):
    list_display = ['request', 'product', 'quantity', 'price', 'total_display', 'is_cancelled']
    list_filter = ['is_cancelled']
    search_fields = ['product__name']

    def total_display(self, obj):
        """
        ИСПРАВЛЕНИЕ #17: Безопасное отображение total
        """
        if obj.price is not None and obj.quantity is not None:
            return f"{obj.price * obj.quantity} сом"
        return "Не рассчитано"

    total_display.short_description = 'Итого'


@admin.register(ReturnRequestItem)
class ReturnRequestItemAdmin(admin.ModelAdmin):
    list_display = ['request', 'product', 'quantity', 'price', 'total_display']
    search_fields = ['product__name']

    def total_display(self, obj):
        """
        ИСПРАВЛЕНИЕ #18: Безопасное отображение total
        """
        if obj.price is not None and obj.quantity is not None:
            return f"{obj.price * obj.quantity} сом"
        return "Не рассчитано"

    total_display.short_description = 'Итого'