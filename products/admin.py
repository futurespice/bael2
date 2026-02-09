# apps/products/admin.py - ИСПРАВЛЕНО v3.1
"""Django Admin для products (ВСЕ ОШИБКИ ФОРМАТИРОВАНИЯ ИСПРАВЛЕНЫ)."""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Expense,
    Product,
    ProductRecipe,
    ProductionBatch,
    ProductImage,
    ProductExpenseRelation,
    PartnerExpense,
)


# =============================================================================
# EXPENSE ADMIN
# =============================================================================

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    """Admin для расходов (физические + накладные)."""

    # Для автозаполнения
    search_fields = ['name']

    list_display = [
        'id',
        'name',
        'expense_type',
        'expense_status',
        'expense_state',
        'price_display',
        'amount_display',
        'is_active',
        'created_at'
    ]

    list_filter = [
        'expense_type',
        'expense_status',
        'expense_state',
        'apply_type',
        'is_active',
        'created_at'
    ]

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
        ('Для физических расходов', {
            'fields': ['unit_type', 'price_per_unit'],
            'classes': ['collapse']
        }),
        ('Зависимости (для Вассалов)', {
            'fields': ['depends_on_suzerain', 'dependency_ratio'],
            'classes': ['collapse']
        }),
        ('Суммы (для накладных)', {
            'fields': ['monthly_amount', 'daily_amount'],
            'classes': ['collapse']
        }),
        ('Статус', {
            'fields': ['is_active']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]

    def price_display(self, obj):
        """Цена за единицу (для физических)."""
        if obj.expense_type == 'physical' and obj.price_per_unit:
            price_formatted = f'{obj.price_per_unit:.2f}'
            unit_display = obj.get_unit_type_display() if obj.unit_type else 'ед'
            return format_html('{} сом/{}', price_formatted, unit_display)
        return '-'

    price_display.short_description = 'Цена'

    def amount_display(self, obj):
        """Сумма (для накладных)."""
        if obj.expense_type == 'overhead':
            if obj.monthly_amount > 0:
                monthly_formatted = f'{obj.monthly_amount:.2f}'
                daily_formatted = f'{obj.daily_amount:.2f}'
                return format_html(
                    '{} сом/мес<br/>{} сом/день',
                    monthly_formatted,
                    daily_formatted
                )
            elif obj.daily_amount > 0:
                daily_formatted = f'{obj.daily_amount:.2f}'
                return format_html('{} сом/день', daily_formatted)
        return '-'

    amount_display.short_description = 'Сумма'


# =============================================================================
# PRODUCT RECIPE ADMIN
# =============================================================================

@admin.register(ProductRecipe)
class ProductRecipeAdmin(admin.ModelAdmin):
    """Admin для рецептов товаров."""

    list_display = [
        'id',
        'product',
        'expense',
        'expense_status_display',
        'quantity_per_unit',
        'proportion',
        'created_at'
    ]

    list_filter = [
        'expense__expense_type',
        'expense__expense_status',
        'created_at'
    ]

    search_fields = ['product__name', 'expense__name']
    readonly_fields = ['created_at']
    autocomplete_fields = ['product', 'expense']

    fieldsets = [
        ('Связь', {
            'fields': ['product', 'expense']
        }),
        ('Пропорции', {
            'fields': ['quantity_per_unit', 'proportion'],
            'description': 'quantity_per_unit для Сюзерена, proportion для остальных'
        }),
        ('Системное', {
            'fields': ['created_at'],
            'classes': ['collapse']
        })
    ]

    def expense_status_display(self, obj):
        """Статус расхода."""
        status = obj.expense.get_expense_status_display()
        if obj.expense.expense_status == 'suzerain':
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', status)
        elif obj.expense.expense_status == 'vassal':
            return format_html('<span style="color: orange;">{}</span>', status)
        return status

    expense_status_display.short_description = 'Статус расхода'


# =============================================================================
# PRODUCT ADMIN
# =============================================================================

class ProductImageInline(admin.TabularInline):
    """Инлайн для изображений."""
    model = ProductImage
    extra = 1
    max_num = 3
    fields = ['image', 'order', 'image_preview']
    readonly_fields = ['image_preview']

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 100px;" />', obj.image.url)
        return '-'

    image_preview.short_description = 'Превью'


class ProductRecipeInline(admin.TabularInline):
    """Инлайн для рецептов."""
    model = ProductRecipe
    extra = 1
    fields = ['expense', 'quantity_per_unit', 'proportion']
    autocomplete_fields = ['expense']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin для товаров."""

    # Для автозаполнения
    search_fields = ['name']

    list_display = [
        'id',
        'name',
        'unit',
        'is_weight_based',
        'is_bonus',
        'cost_display',
        'price_display',
        'profit_display',
        'stock_quantity',
        'is_active',
        'is_available'
    ]

    list_filter = [
        'unit',
        'is_weight_based',
        'is_bonus',
        'is_active',
        'is_available',
        'created_at'
    ]

    readonly_fields = [
        'average_cost_price',
        'final_price',
        'price_per_100g',
        'profit_per_unit',
        'created_at',
        'updated_at'
    ]

    inlines = [ProductImageInline, ProductRecipeInline]

    fieldsets = [
        ('Основное', {
            'fields': ['name', 'description', 'unit', 'is_weight_based', 'is_bonus']
        }),
        ('Ценообразование', {
            'fields': [
                'average_cost_price',
                'markup_percentage',
                'manual_price',
                'final_price',
                'price_per_100g',
                'profit_per_unit'
            ]
        }),
        ('Склад', {
            'fields': ['stock_quantity']
        }),
        ('Статус', {
            'fields': ['is_active', 'is_available', 'popularity_weight']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]

    def cost_display(self, obj):
        """Себестоимость."""
        cost_formatted = f'{obj.average_cost_price:.2f}'
        return format_html('{} сом', cost_formatted)

    cost_display.short_description = 'Себестоимость'

    def price_display(self, obj):
        """Цена продажи."""
        price_formatted = f'{obj.final_price:.2f}'
        return format_html('{} сом', price_formatted)

    price_display.short_description = 'Цена'

    def profit_display(self, obj):
        """Прибыль."""
        profit = obj.profit_per_unit
        color = 'green' if profit > 0 else 'red'
        profit_formatted = f'{profit:.2f}'
        return format_html(
            '<span style="color: {};">{} сом</span>',
            color,
            profit_formatted
        )

    profit_display.short_description = 'Прибыль/шт'


# =============================================================================
# PRODUCTION BATCH ADMIN
# =============================================================================

@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    """Admin для производственных партий."""

    list_display = [
        'id',
        'date',
        'product',
        'quantity_produced',
        'cost_per_unit_display',
        'total_cost_display',
        'input_type',
        'created_at'
    ]

    list_filter = ['date', 'input_type', 'product']
    search_fields = ['product__name', 'notes']

    readonly_fields = [
        'total_physical_cost',
        'total_overhead_cost',
        'cost_per_unit',
        'total_cost_display',
        'created_at',
        'updated_at'
    ]

    fieldsets = [
        ('Основное', {
            'fields': ['product', 'date', 'quantity_produced', 'input_type']
        }),
        ('Расходы', {
            'fields': [
                'total_physical_cost',
                'total_overhead_cost',
                'total_cost_display'
            ]
        }),
        ('Результат', {
            'fields': ['cost_per_unit']
        }),
        ('Заметки', {
            'fields': ['notes']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]

    def cost_per_unit_display(self, obj):
        """Себестоимость за единицу."""
        cost_formatted = f'{obj.cost_per_unit:.2f}'
        return format_html('{} сом', cost_formatted)

    cost_per_unit_display.short_description = 'Себестоимость/шт'

    def total_cost_display(self, obj):
        """Общая стоимость."""
        total = obj.total_physical_cost + obj.total_overhead_cost
        total_formatted = f'{total:.2f}'
        return format_html('{} сом', total_formatted)

    total_cost_display.short_description = 'Общая стоимость'


# =============================================================================
# PRODUCT IMAGE ADMIN
# =============================================================================

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
            return format_html('<img src="{}" style="max-height: 100px;" />', obj.image.url)
        return '-'

    image_preview.short_description = 'Превью'


# =============================================================================
# PARTNER EXPENSE ADMIN
# =============================================================================

@admin.register(PartnerExpense)
class PartnerExpenseAdmin(admin.ModelAdmin):
    """Admin для расходов партнёров."""

    list_display = [
        'id',
        'partner',
        'amount_display',
        'description_short',
        'date',
        'created_at'
    ]

    list_filter = ['partner', 'date', 'created_at']
    search_fields = ['description', 'partner__email']
    readonly_fields = ['created_at']
    autocomplete_fields = ['partner']

    def amount_display(self, obj):
        """Сумма."""
        amount_formatted = f'{obj.amount:.2f}'
        return format_html('{} сом', amount_formatted)

    amount_display.short_description = 'Сумма'

    def description_short(self, obj):
        """Короткое описание."""
        if len(obj.description) > 50:
            return f'{obj.description[:50]}...'
        return obj.description

    description_short.short_description = 'Описание'


# =============================================================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ
# =============================================================================

@admin.register(ProductExpenseRelation)
class ProductExpenseRelationAdmin(admin.ModelAdmin):
    """
    Admin для связей товар-расход (УСТАРЕЛО).
    Используйте ProductRecipe вместо этого.
    """

    list_display = ['id', 'product', 'expense', 'proportion', 'created_at']
    list_filter = ['expense__expense_type']
    search_fields = ['product__name', 'expense__name']
    readonly_fields = ['created_at']
    autocomplete_fields = ['product', 'expense']