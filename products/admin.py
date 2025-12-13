# apps/products/admin.py
"""Django Admin для products."""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Expense,
    Product,
    ProductionBatch,
    ProductImage,
    ProductExpenseRelation
)


class ProductImageInline(admin.TabularInline):
    """Инлайн для изображений."""
    model = ProductImage
    extra = 1
    max_num = 3
    fields = ['image', 'order']
    readonly_fields = []


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    """Admin для расходов."""

    list_display = [
        'name',
        'expense_type',
        'expense_status',
        'daily_amount',
        'monthly_amount',
        'is_active',
        'created_at'
    ]

    list_filter = [
        'expense_type',
        'expense_status',
        'is_active',
        'created_at'
    ]

    search_fields = ['name', 'description']

    readonly_fields = ['created_at', 'updated_at']

    fieldsets = [
        ('Основное', {
            'fields': ['name', 'description']
        }),
        ('Классификация', {
            'fields': [
                'expense_type',
                'expense_status',
                'expense_state',
                'apply_type'
            ]
        }),
        ('Суммы', {
            'fields': ['daily_amount', 'monthly_amount']
        }),
        ('Статус', {
            'fields': ['is_active']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin для товаров."""

    list_display = [
        'name',
        'unit',
        'average_cost_price',
        'markup_percentage',
        'final_price_display',
        'profit_display',
        'stock_quantity',
        'is_active'
    ]

    list_filter = [
        'unit',
        'is_weight_based',
        'is_bonus',
        'is_active',
        'is_available'
    ]

    search_fields = ['name', 'description']

    readonly_fields = [
        'average_cost_price',
        'final_price',
        'price_per_100g',
        'profit_display',
        'created_at',
        'updated_at'
    ]

    inlines = [ProductImageInline]

    fieldsets = [
        ('Основное', {
            'fields': ['name', 'description']
        }),
        ('Тип', {
            'fields': ['unit', 'is_weight_based', 'is_bonus']
        }),
        ('Ценообразование', {
            'fields': [
                'average_cost_price',
                'markup_percentage',
                'final_price',
                'price_per_100g',
                'profit_display'
            ]
        }),
        ('Склад', {
            'fields': ['stock_quantity', 'is_active', 'is_available']
        }),
        ('Популярность', {
            'fields': ['popularity_weight'],
            'classes': ['collapse']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]

    def final_price_display(self, obj):
        """Цена продажи."""
        # ИСПРАВЛЕНО
        price_formatted = f'{obj.final_price:.2f}'
        return format_html(
            '<strong>{} сом</strong>',
            price_formatted
        )

    final_price_display.short_description = 'Цена продажи'

    def profit_display(self, obj):
        """Прибыль."""
        profit = obj.profit_per_unit
        color = 'green' if profit > 0 else 'red'
        # ИСПРАВЛЕНО
        profit_formatted = f'{profit:.2f}'
        return format_html(
            '<span style="color: {};">{} сом</span>',
            color,
            profit_formatted
        )

    profit_display.short_description = 'Прибыль/шт'


@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    """Admin для производства."""

    list_display = [
        'date',
        'product',
        'quantity_produced',
        'cost_price_calculated',
        'total_expenses_display',
        'created_at'
    ]

    list_filter = ['date', 'product']

    search_fields = ['product__name', 'notes']

    readonly_fields = [
        'total_daily_expenses',
        'total_monthly_expenses_per_day',
        'cost_price_calculated',
        'total_expenses_display',
        'created_at'
    ]

    fieldsets = [
        ('Основное', {
            'fields': ['product', 'date', 'quantity_produced']
        }),
        ('Расходы', {
            'fields': [
                'total_daily_expenses',
                'total_monthly_expenses_per_day',
                'total_expenses_display'
            ]
        }),
        ('Результат', {
            'fields': ['cost_price_calculated']
        }),
        ('Заметки', {
            'fields': ['notes']
        }),
        ('Системное', {
            'fields': ['created_at'],
            'classes': ['collapse']
        })
    ]

    def total_expenses_display(self, obj):
        """Общие расходы."""
        total = obj.total_daily_expenses + obj.total_monthly_expenses_per_day
        # ИСПРАВЛЕНО
        total_formatted = f'{total:.2f}'
        return format_html('{} сом', total_formatted)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    """Admin для изображений."""

    list_display = ['product', 'order', 'image_preview', 'created_at']

    list_filter = ['created_at']

    search_fields = ['product__name']

    readonly_fields = ['image_preview', 'created_at']

    def image_preview(self, obj):
        """Превью."""
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 100px;" />',
                obj.image.url
            )
        return '-'

    image_preview.short_description = 'Превью'


@admin.register(ProductExpenseRelation)
class ProductExpenseRelationAdmin(admin.ModelAdmin):
    """Admin для связей."""

    list_display = ['product', 'expense', 'proportion', 'created_at']

    list_filter = ['expense__expense_type']

    search_fields = ['product__name', 'expense__name']

    readonly_fields = ['created_at']

    autocomplete_fields = ['product', 'expense']