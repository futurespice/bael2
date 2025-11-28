# apps/products/admin.py
"""
Административный интерфейс для модуля products.

Регистрирует модели:
- Expense (Расходы)
- Product (Товары)
- Recipe (Рецепты)
- ProductionRecord (Записи производства)
- BonusHistory (История бонусов)
- StoreProductCounter (Счётчики товаров)
- DefectiveProduct (Бракованные товары)
- ProductCostSnapshot (Кеш себестоимости)
"""

from decimal import Decimal

from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html

from .models import (
    Product,
    ProductImage,
    Expense,
    Recipe,
    ProductExpenseRelation,
    ProductCostSnapshot,
    ProductionRecord,
    ProductionItem,
    MechanicalExpenseEntry,
    BonusHistory,
    StoreProductCounter,
    DefectiveProduct,
    ExpenseType,
    AccountingMode,
    DefectStatus,
)


# =============================================================================
# EXPENSE ADMIN
# =============================================================================

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    """Админка расходов (ингредиенты и накладные)."""

    list_display = [
        'name',
        'expense_type',
        'accounting_mode',
        'status',
        'state',
        'price_per_unit_display',
        'monthly_amount_display',
        'is_active',
    ]
    list_filter = [
        'expense_type',
        'accounting_mode',
        'status',
        'state',
        'is_active',
    ]
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['is_active']
    ordering = ['-created_at']

    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'expense_type', 'accounting_mode', 'status', 'state')
        }),
        ('Физические расходы (Ингредиенты)', {
            'fields': ('price_per_unit', 'unit'),
            'classes': ('collapse',),
            'description': 'Заполняется для типа расхода "Физический"'
        }),
        ('Накладные расходы', {
            'fields': ('monthly_amount', 'apply_type'),
            'classes': ('collapse',),
            'description': 'Заполняется для типа расхода "Накладной"'
        }),
        ('Статус', {
            'fields': ('is_active',)
        }),
        ('Системная информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def price_per_unit_display(self, obj: Expense) -> str:
        """Отображение цены за единицу."""
        if obj.price_per_unit and obj.unit:
            return f"{obj.price_per_unit} сом/{obj.get_unit_display()}"
        return "—"

    price_per_unit_display.short_description = 'Цена за единицу'

    def monthly_amount_display(self, obj: Expense) -> str:
        """Отображение месячной суммы."""
        if obj.monthly_amount:
            return f"{obj.monthly_amount} сом/мес"
        return "—"

    monthly_amount_display.short_description = 'Сумма в месяц'


# =============================================================================
# PRODUCT ADMIN
# =============================================================================

class ProductImageInline(admin.TabularInline):
    """Инлайн для изображений товара."""
    model = ProductImage
    extra = 1
    max_num = 3
    fields = ['image', 'position']


class RecipeInline(admin.TabularInline):
    """Инлайн для рецептов (котловой метод)."""
    model = Recipe
    extra = 1
    fields = ['expense', 'ingredient_amount', 'output_quantity', 'proportion']
    readonly_fields = ['proportion']
    autocomplete_fields = ['expense']
    verbose_name = "Рецепт (Ингредиент)"
    verbose_name_plural = "Рецептура (Ингредиенты)"


class ProductExpenseRelationInline(admin.TabularInline):
    """Legacy инлайн для обратной совместимости."""
    model = ProductExpenseRelation
    extra = 0
    fields = ['expense', 'proportion']
    autocomplete_fields = ['expense']
    verbose_name = "Связь с расходом (Legacy)"
    verbose_name_plural = "Связи с расходами (Legacy)"
    classes = ('collapse',)


class ProductCostSnapshotInline(admin.StackedInline):
    """Инлайн для кеша себестоимости."""
    model = ProductCostSnapshot
    readonly_fields = [
        'cost_price',
        'markup_amount',
        'ingredient_expense',
        'overhead_expense',
        'total_expense',
        'revenue',
        'profit',
        'last_calculated_at',
        'is_outdated',
    ]
    can_delete = False
    extra = 0
    classes = ('collapse',)
    verbose_name = "Кеш себестоимости"
    verbose_name_plural = "Кеш себестоимости"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Админка товаров."""

    list_display = [
        'name',
        'final_price_display',
        'cost_price_display',
        'markup_percentage_display',
        'is_weight_based',
        'is_active',
        'stock_quantity',
    ]
    list_filter = ['is_weight_based', 'is_active', 'is_available', 'unit']
    search_fields = ['name', 'description']
    readonly_fields = [
        'price_per_100g',
        'final_price',
        'cost_price',
        'popularity_weight',
        'created_at',
        'updated_at',
    ]
    inlines = [
        ProductImageInline,
        RecipeInline,
        ProductExpenseRelationInline,
        ProductCostSnapshotInline,
    ]
    save_on_top = True
    list_editable = ['is_active']
    ordering = ['name']

    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'image')
        }),
        ('Тип товара', {
            'fields': ('unit', 'is_weight_based')
        }),
        ('Ценообразование', {
            'fields': (
                'base_price',
                'cost_price',
                'markup_percentage',
                'final_price',
                'price_per_100g',
            ),
            'description': 'Итоговая цена = себестоимость × (1 + наценка/100)'
        }),
        ('Аналитика', {
            'fields': ('popularity_weight',),
            'classes': ('collapse',),
            'description': 'Коэффициент для распределения накладных расходов'
        }),
        ('Запасы', {
            'fields': ('stock_quantity',)
        }),
        ('Статус', {
            'fields': ('is_active', 'is_available')
        }),
        ('Системная информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def final_price_display(self, obj: Product) -> str:
        """Отображение итоговой цены."""
        return f"{obj.final_price} сом"

    final_price_display.short_description = 'Итоговая цена'
    final_price_display.admin_order_field = 'final_price'

    def cost_price_display(self, obj: Product) -> str:
        """Отображение себестоимости."""
        return f"{obj.cost_price} сом"

    cost_price_display.short_description = 'Себестоимость'
    cost_price_display.admin_order_field = 'cost_price'

    def markup_percentage_display(self, obj: Product) -> str:
        """Отображение наценки."""
        return f"{obj.markup_percentage}%"

    markup_percentage_display.short_description = 'Наценка'
    markup_percentage_display.admin_order_field = 'markup_percentage'


# =============================================================================
# RECIPE ADMIN
# =============================================================================

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    """Админка рецептов."""

    list_display = [
        'product',
        'expense',
        'ingredient_amount',
        'output_quantity',
        'proportion',
        'cost_per_unit_display',
    ]
    list_filter = ['expense__expense_type', 'product__is_weight_based']
    search_fields = ['product__name', 'expense__name']
    autocomplete_fields = ['product', 'expense']
    readonly_fields = ['proportion', 'created_at', 'updated_at']
    ordering = ['product__name', 'expense__name']

    def cost_per_unit_display(self, obj: Recipe) -> str:
        """Стоимость ингредиента на единицу товара."""
        cost = obj.get_ingredient_cost_per_unit()
        return f"{cost} сом"

    cost_per_unit_display.short_description = 'Стоимость на ед.'


# =============================================================================
# PRODUCTION ADMIN
# =============================================================================

class ProductionItemInline(admin.TabularInline):
    """Инлайн для позиций производства."""
    model = ProductionItem
    extra = 0
    readonly_fields = [
        'ingredient_cost',
        'overhead_cost',
        'total_cost',
        'cost_price',
        'revenue',
        'net_profit',
    ]
    fields = [
        'product',
        'quantity_produced',
        'suzerain_amount',
        'ingredient_cost',
        'overhead_cost',
        'total_cost',
        'cost_price',
        'revenue',
        'net_profit',
    ]
    autocomplete_fields = ['product']


class MechanicalExpenseEntryInline(admin.TabularInline):
    """Инлайн для механических расходов."""
    model = MechanicalExpenseEntry
    extra = 1
    fields = ['expense', 'amount_spent', 'comment']
    autocomplete_fields = ['expense']


@admin.register(ProductionRecord)
class ProductionRecordAdmin(admin.ModelAdmin):
    """Админка записей производства."""

    list_display = [
        'partner',
        'date',
        'items_count',
        'total_quantity_display',
        'total_cost_display',
        'total_revenue_display',
        'net_profit_display',
        'created_at',
    ]
    list_filter = ['date', 'partner']
    search_fields = ['partner__email', 'partner__first_name', 'partner__last_name']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ProductionItemInline, MechanicalExpenseEntryInline]
    date_hierarchy = 'date'
    ordering = ['-date']

    def items_count(self, obj: ProductionRecord) -> int:
        """Количество позиций."""
        return obj.items.count()

    items_count.short_description = 'Позиций'

    def total_quantity_display(self, obj: ProductionRecord) -> str:
        """Общее количество."""
        val = obj.get_total_quantity()
        return f"{val}"

    total_quantity_display.short_description = 'Количество'

    def total_cost_display(self, obj: ProductionRecord) -> str:
        """Общая себестоимость."""
        val = obj.get_total_cost()
        return f"{val} сом"

    total_cost_display.short_description = 'Себестоимость'

    def total_revenue_display(self, obj: ProductionRecord) -> str:
        """Общая выручка."""
        val = obj.get_total_revenue()
        return f"{val} сом"

    total_revenue_display.short_description = 'Выручка'

    def net_profit_display(self, obj: ProductionRecord) -> str:
        """Чистая прибыль."""
        val = obj.get_net_profit()
        color = 'green' if val >= 0 else 'red'
        return format_html('<span style="color: {};">{} сом</span>', color, val)

    net_profit_display.short_description = 'Прибыль'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('partner').prefetch_related('items')


# =============================================================================
# BONUS ADMIN
# =============================================================================

@admin.register(BonusHistory)
class BonusHistoryAdmin(admin.ModelAdmin):
    """Админка истории бонусов."""

    list_display = [
        'store',
        'partner',
        'product',
        'quantity',
        'bonus_value_display',
        'order_link',
        'created_at',
    ]
    list_filter = ['created_at', 'store', 'partner']
    search_fields = ['store__name', 'partner__email', 'product__name']
    readonly_fields = ['bonus_value', 'created_at']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    def bonus_value_display(self, obj: BonusHistory) -> str:
        """Стоимость бонуса."""
        return f"{obj.bonus_value} сом"

    bonus_value_display.short_description = 'Стоимость'

    def order_link(self, obj: BonusHistory) -> str:
        """Ссылка на заказ."""
        if obj.order:
            return format_html(
                '<a href="/admin/orders/storeorder/{}/change/">Заказ #{}</a>',
                obj.order.id,
                obj.order.id
            )
        return "—"

    order_link.short_description = 'Заказ'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('store', 'partner', 'product', 'order')


@admin.register(StoreProductCounter)
class StoreProductCounterAdmin(admin.ModelAdmin):
    """Админка счётчиков товаров для бонусов."""

    list_display = [
        'store',
        'partner',
        'product',
        'total_count',
        'bonuses_given',
        'pending_bonuses_display',
        'progress_display',
        'last_bonus_at',
    ]
    list_filter = ['store', 'partner']
    search_fields = ['store__name', 'partner__email', 'product__name']
    readonly_fields = ['last_bonus_at', 'created_at', 'updated_at']
    ordering = ['-total_count']

    def pending_bonuses_display(self, obj: StoreProductCounter) -> str:
        """Количество доступных бонусов."""
        pending = obj.get_pending_bonus_count()
        if pending > 0:
            return format_html(
                '<span style="color: green; font-weight: bold;">{}</span>',
                pending
            )
        return "0"

    pending_bonuses_display.short_description = 'Доступно'

    def progress_display(self, obj: StoreProductCounter) -> str:
        """Прогресс до следующего бонуса."""
        remainder = obj.total_count % 21
        progress_pct = round(remainder / 21 * 100)
        return format_html(
            '<div style="width:100px; background:#eee; border-radius:4px;">'
            '<div style="width:{}%; background:#4CAF50; height:10px; border-radius:4px;"></div>'
            '</div>'
            '<small>{}/21</small>',
            progress_pct,
            remainder
        )

    progress_display.short_description = 'Прогресс'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('store', 'partner', 'product')


# =============================================================================
# DEFECTIVE PRODUCT ADMIN
# =============================================================================

@admin.register(DefectiveProduct)
class DefectiveProductAdmin(admin.ModelAdmin):
    """Админка бракованных товаров."""

    list_display = [
        'product',
        'partner',
        'quantity',
        'status_badge',
        'reason_short',
        'created_at',
        'resolved_at',
    ]
    list_filter = ['status', 'created_at', 'partner']
    search_fields = ['product__name', 'partner__email', 'reason']
    readonly_fields = ['created_at', 'updated_at', 'resolved_at']
    ordering = ['-created_at']
    actions = ['confirm_defects', 'reject_defects']

    fieldsets = (
        ('Основная информация', {
            'fields': ('partner', 'product', 'quantity', 'reason')
        }),
        ('Статус', {
            'fields': ('status', 'resolved_at')
        }),
        ('Системная информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def status_badge(self, obj: DefectiveProduct) -> str:
        """Бейдж статуса."""
        colors = {
            DefectStatus.REPORTED: '#FF9800',
            DefectStatus.CONFIRMED: '#4CAF50',
            DefectStatus.REJECTED: '#F44336',
        }
        color = colors.get(obj.status, '#999')
        return format_html(
            '<span style="background:{}; color:white; padding:2px 8px; '
            'border-radius:4px; font-size:11px;">{}</span>',
            color,
            obj.get_status_display()
        )

    status_badge.short_description = 'Статус'

    def reason_short(self, obj: DefectiveProduct) -> str:
        """Краткая причина брака."""
        if len(obj.reason) > 50:
            return f"{obj.reason[:50]}..."
        return obj.reason

    reason_short.short_description = 'Причина'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('partner', 'product')

    @admin.action(description='Подтвердить выбранные заявки')
    def confirm_defects(self, request, queryset):
        """Массовое подтверждение брака."""
        count = 0
        for defect in queryset.filter(status=DefectStatus.REPORTED):
            defect.confirm()
            count += 1
        self.message_user(request, f'Подтверждено {count} заявок.')

    @admin.action(description='Отклонить выбранные заявки')
    def reject_defects(self, request, queryset):
        """Массовое отклонение брака."""
        count = 0
        for defect in queryset.filter(status=DefectStatus.REPORTED):
            defect.reject()
            count += 1
        self.message_user(request, f'Отклонено {count} заявок.')


# =============================================================================
# PRODUCT COST SNAPSHOT ADMIN
# =============================================================================

@admin.register(ProductCostSnapshot)
class ProductCostSnapshotAdmin(admin.ModelAdmin):
    """Админка кеша себестоимости."""

    list_display = [
        'product',
        'cost_price',
        'markup_amount',
        'total_expense',
        'revenue',
        'profit_display',
        'is_outdated_badge',
        'last_calculated_at',
    ]
    list_filter = ['is_outdated', 'last_calculated_at']
    search_fields = ['product__name']
    readonly_fields = [
        'product',
        'cost_price',
        'markup_amount',
        'ingredient_expense',
        'overhead_expense',
        'total_expense',
        'revenue',
        'profit',
        'last_calculated_at',
        'is_outdated',
    ]
    ordering = ['product__name']
    actions = ['mark_as_outdated', 'recalculate_snapshots']

    def profit_display(self, obj: ProductCostSnapshot) -> str:
        """Отображение прибыли."""
        color = 'green' if obj.profit >= 0 else 'red'
        return format_html(
            '<span style="color: {};">{} сом</span>',
            color,
            obj.profit
        )

    profit_display.short_description = 'Прибыль'

    def is_outdated_badge(self, obj: ProductCostSnapshot) -> str:
        """Бейдж устаревания."""
        if obj.is_outdated:
            return format_html(
                '<span style="color: orange;">⚠ Устарел</span>'
            )
        return format_html(
            '<span style="color: green;">✓ Актуален</span>'
        )

    is_outdated_badge.short_description = 'Статус'

    @admin.action(description='Пометить как устаревшие')
    def mark_as_outdated(self, request, queryset):
        """Пометить снапшоты как требующие пересчёта."""
        count = queryset.update(is_outdated=True)
        self.message_user(request, f'Помечено как устаревшие: {count} записей.')

    @admin.action(description='Пересчитать выбранные')
    def recalculate_snapshots(self, request, queryset):
        """Пересчитать выбранные снапшоты."""
        from .services import CostCalculator

        count = 0
        for snapshot in queryset:
            CostCalculator.update_product_snapshot(snapshot.product)
            count += 1
        self.message_user(request, f'Пересчитано: {count} записей.')
