# apps/products/serializers.py
"""
Сериализаторы для модуля products.

Особенности:
- Динамическое отображение цены в зависимости от роли пользователя
- Поддержка "котлового" метода для рецептов
- Сериализаторы для экранов "Динамичный/Статичный учёт"
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

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
    ExpenseStatus,
    ExpenseState,
)
from .services import CostCalculator


# =============================================================================
# EXPENSE SERIALIZERS
# =============================================================================

class ExpenseListSerializer(serializers.ModelSerializer):
    """Краткий сериализатор расхода для списков."""

    expense_type_display = serializers.CharField(
        source='get_expense_type_display',
        read_only=True
    )
    accounting_mode_display = serializers.CharField(
        source='get_accounting_mode_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    state_display = serializers.CharField(
        source='get_state_display',
        read_only=True
    )
    daily_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = Expense
        fields = [
            'id',
            'name',
            'expense_type',
            'expense_type_display',
            'accounting_mode',
            'accounting_mode_display',
            'price_per_unit',
            'unit',
            'monthly_amount',
            'daily_amount',
            'status',
            'status_display',
            'state',
            'state_display',
            'apply_type',
            'is_active',
        ]


class ExpenseDetailSerializer(serializers.ModelSerializer):
    """Полный сериализатор расхода для создания/редактирования."""

    expense_type_display = serializers.CharField(
        source='get_expense_type_display',
        read_only=True
    )
    accounting_mode_display = serializers.CharField(
        source='get_accounting_mode_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    state_display = serializers.CharField(
        source='get_state_display',
        read_only=True
    )
    daily_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    products_count = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            'id',
            'name',
            'expense_type',
            'expense_type_display',
            'accounting_mode',
            'accounting_mode_display',
            'price_per_unit',
            'unit',
            'monthly_amount',
            'daily_amount',
            'status',
            'status_display',
            'state',
            'state_display',
            'apply_type',
            'is_active',
            'products_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    @extend_schema_field(OpenApiTypes.INT)
    def get_products_count(self, obj: Expense) -> int:
        """Количество товаров, использующих этот расход."""
        return obj.recipes.count() + obj.product_relations.count()

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация в зависимости от типа расхода."""
        expense_type = data.get('expense_type', getattr(self.instance, 'expense_type', None))

        if expense_type == ExpenseType.PHYSICAL:
            if not data.get('price_per_unit'):
                raise serializers.ValidationError({
                    'price_per_unit': 'Обязательно для физических расходов.'
                })
            if not data.get('unit'):
                raise serializers.ValidationError({
                    'unit': 'Обязательно для физических расходов.'
                })
            # Физические всегда динамичные
            data['accounting_mode'] = AccountingMode.DYNAMIC

        elif expense_type == ExpenseType.OVERHEAD:
            state = data.get('state', getattr(self.instance, 'state', ExpenseState.AUTOMATIC))
            if state == ExpenseState.AUTOMATIC and not data.get('monthly_amount'):
                raise serializers.ValidationError({
                    'monthly_amount': 'Обязательно для автоматических накладных расходов.'
                })
            # Накладные по умолчанию статичные
            if 'accounting_mode' not in data:
                data['accounting_mode'] = AccountingMode.STATIC

        return data


class ExpenseCreateSerializer(ExpenseDetailSerializer):
    """Сериализатор для создания расхода."""

    class Meta(ExpenseDetailSerializer.Meta):
        read_only_fields = ['created_at', 'updated_at', 'daily_amount']


# =============================================================================
# RECIPE SERIALIZERS (Котловой метод)
# =============================================================================

class RecipeSerializer(serializers.ModelSerializer):
    """
    Сериализатор рецепта с поддержкой "котлового" метода.

    Пользователь вводит:
    - ingredient_amount: 50 кг муки
    - output_quantity: 5000 булочек

    Пропорция вычисляется автоматически: 50/5000 = 0.01
    """

    expense_name = serializers.CharField(
        source='expense.name',
        read_only=True
    )
    expense_unit = serializers.CharField(
        source='expense.unit',
        read_only=True
    )
    expense_price = serializers.DecimalField(
        source='expense.price_per_unit',
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    cost_per_unit = serializers.SerializerMethodField()

    class Meta:
        model = Recipe
        fields = [
            'id',
            'product',
            'expense',
            'expense_name',
            'expense_unit',
            'expense_price',
            'ingredient_amount',
            'output_quantity',
            'proportion',
            'cost_per_unit',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['proportion', 'created_at', 'updated_at']

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_cost_per_unit(self, obj: Recipe) -> Decimal:
        """Стоимость ингредиента на единицу товара."""
        return obj.get_ingredient_cost_per_unit()

    def validate_expense(self, value: Expense) -> Expense:
        """Проверка, что расход является ингредиентом."""
        if value.expense_type != ExpenseType.PHYSICAL:
            raise serializers.ValidationError(
                'Можно привязывать только физические расходы (ингредиенты).'
            )
        return value

    def validate_output_quantity(self, value: Decimal) -> Decimal:
        """Проверка положительного количества продукции."""
        if value <= 0:
            raise serializers.ValidationError(
                'Количество продукции должно быть больше 0.'
            )
        return value


class RecipeCreateSerializer(RecipeSerializer):
    """Сериализатор для создания рецепта."""

    class Meta(RecipeSerializer.Meta):
        read_only_fields = ['proportion', 'created_at', 'updated_at', 'cost_per_unit']


# =============================================================================
# PRODUCT SERIALIZERS
# =============================================================================

class ProductImageSerializer(serializers.ModelSerializer):
    """Сериализатор изображения товара."""

    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'position']


class ProductListSerializer(serializers.ModelSerializer):
    """
    Краткий сериализатор товара для списков.

    Особенность: цена отображается в зависимости от роли пользователя.
    - Админ видит себестоимость (cost_price)
    - Партнёр/Магазин видят итоговую цену (final_price)
    """

    images = ProductImageSerializer(many=True, read_only=True)
    unit_display = serializers.CharField(
        source='get_unit_display',
        read_only=True
    )
    display_price = serializers.SerializerMethodField()
    minimum_order_quantity = serializers.SerializerMethodField()
    order_step = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'description',
            'unit',
            'unit_display',
            'display_price',
            'is_weight_based',
            'price_per_100g',
            'is_active',
            'is_available',
            'stock_quantity',
            'images',
            'minimum_order_quantity',
            'order_step',
            'created_at',
        ]

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_display_price(self, obj: Product) -> Decimal:
        """
        Цена для отображения в зависимости от роли.

        - Админ: себестоимость
        - Остальные: итоговая цена с наценкой
        """
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            role = getattr(request.user, 'role', None)
            if role == 'admin':
                return obj.cost_price
        return obj.final_price

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_minimum_order_quantity(self, obj: Product) -> Decimal:
        """Минимальное количество для заказа."""
        return obj.get_minimum_order_quantity()

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_order_step(self, obj: Product) -> Decimal:
        """Шаг заказа."""
        return obj.get_order_step()


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Полный сериализатор товара с рецептами и ценообразованием.
    """

    images = ProductImageSerializer(many=True, read_only=True)
    recipes = RecipeSerializer(many=True, read_only=True)
    unit_display = serializers.CharField(
        source='get_unit_display',
        read_only=True
    )
    display_price = serializers.SerializerMethodField()
    minimum_order_quantity = serializers.SerializerMethodField()
    order_step = serializers.SerializerMethodField()

    # Для загрузки изображений
    uploaded_images = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False,
        max_length=3
    )

    # Информация о себестоимости (только для админа)
    cost_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'description',
            'unit',
            'unit_display',
            'is_weight_based',
            # Цены
            'base_price',
            'cost_price',
            'markup_percentage',
            'final_price',
            'display_price',
            'price_per_100g',
            # Склад
            'stock_quantity',
            'is_active',
            'is_available',
            # Медиа
            'image',
            'images',
            'uploaded_images',
            # Рецепты
            'recipes',
            # Метаданные
            'popularity_weight',
            'minimum_order_quantity',
            'order_step',
            'cost_breakdown',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'cost_price',
            'final_price',
            'price_per_100g',
            'popularity_weight',
            'created_at',
            'updated_at',
        ]

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_display_price(self, obj: Product) -> Decimal:
        """Цена для отображения в зависимости от роли."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            role = getattr(request.user, 'role', None)
            if role == 'admin':
                return obj.cost_price
        return obj.final_price

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_minimum_order_quantity(self, obj: Product) -> Decimal:
        """Минимальное количество для заказа."""
        return obj.get_minimum_order_quantity()

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_order_step(self, obj: Product) -> Decimal:
        """Шаг заказа."""
        return obj.get_order_step()

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_cost_breakdown(self, obj: Product) -> Optional[Dict]:
        """
        Детализация себестоимости (только для админа).
        """
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            return None

        if getattr(request.user, 'role', None) != 'admin':
            return None

        # Собираем детализацию из рецептов
        ingredients = []
        total_ingredient_cost = Decimal('0')

        for recipe in obj.recipes.select_related('expense').filter(expense__is_active=True):
            cost = recipe.get_ingredient_cost_per_unit()
            total_ingredient_cost += cost
            ingredients.append({
                'name': recipe.expense.name,
                'proportion': str(recipe.proportion),
                'price_per_unit': str(recipe.expense.price_per_unit or 0),
                'cost': str(cost),
            })

        return {
            'ingredients': ingredients,
            'total_ingredient_cost': str(total_ingredient_cost),
            'markup_percentage': str(obj.markup_percentage),
            'markup_amount': str(
                (total_ingredient_cost * obj.markup_percentage / 100).quantize(Decimal('0.01'))
                if obj.markup_percentage > 0 else 0
            ),
        }

    def validate_uploaded_images(self, value: List) -> List:
        """Проверка количества изображений."""
        if len(value) > 3:
            raise serializers.ValidationError('Максимум 3 изображения.')
        return value

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация товара."""
        is_weight_based = data.get(
            'is_weight_based',
            getattr(self.instance, 'is_weight_based', False)
        )
        unit = data.get('unit', getattr(self.instance, 'unit', 'piece'))

        # Весовые товары должны быть в кг
        if is_weight_based and unit != 'kg':
            raise serializers.ValidationError({
                'unit': 'Весовые товары должны иметь единицу измерения "Килограмм".'
            })

        # Нельзя сменить весовой на штучный
        if self.instance and self.instance.is_weight_based and not is_weight_based:
            raise serializers.ValidationError({
                'is_weight_based': 'Нельзя изменить весовой товар на штучный.'
            })

        return data

    def create(self, validated_data: Dict[str, Any]) -> Product:
        """Создание товара с изображениями."""
        uploaded_images = validated_data.pop('uploaded_images', [])
        product = super().create(validated_data)

        for idx, image in enumerate(uploaded_images):
            ProductImage.objects.create(product=product, image=image, position=idx)

        return product

    def update(self, instance: Product, validated_data: Dict[str, Any]) -> Product:
        """Обновление товара с пересчётом цен."""
        uploaded_images = validated_data.pop('uploaded_images', None)

        # Обновляем товар
        product = super().update(instance, validated_data)

        # Обновляем изображения, если переданы
        if uploaded_images is not None:
            product.images.all().delete()
            for idx, image in enumerate(uploaded_images):
                ProductImage.objects.create(product=product, image=image, position=idx)

        # Пересчитываем себестоимость, если изменилась наценка
        if 'markup_percentage' in validated_data:
            CostCalculator.update_product_cost_and_price(product)

        return product


class ProductCreateSerializer(ProductDetailSerializer):
    """Сериализатор для создания товара."""

    class Meta(ProductDetailSerializer.Meta):
        read_only_fields = [
            'cost_price',
            'final_price',
            'price_per_100g',
            'popularity_weight',
            'created_at',
            'updated_at',
        ]


# =============================================================================
# COST TABLE SERIALIZER (Таблица себестоимости)
# =============================================================================

class CostTableSerializer(serializers.Serializer):
    """
    Сериализатор для таблицы себестоимости.

    Соответствует экрану "Динамичный учёт" → Секция "Товары":
    | Название | Наценка | Себ-сть | Расход | Доход |
    """

    product_id = serializers.IntegerField()
    name = serializers.CharField()
    markup = serializers.DecimalField(max_digits=12, decimal_places=2)
    cost_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    expense = serializers.DecimalField(max_digits=12, decimal_places=2)
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    profit = serializers.DecimalField(max_digits=12, decimal_places=2)
    is_weight_based = serializers.BooleanField()


class ProductCostSnapshotSerializer(serializers.ModelSerializer):
    """Сериализатор кеша себестоимости."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    product_id = serializers.IntegerField(source='product.id', read_only=True)

    class Meta:
        model = ProductCostSnapshot
        fields = [
            'id',
            'product_id',
            'product_name',
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


# =============================================================================
# PRODUCTION SERIALIZERS
# =============================================================================

class MechanicalExpenseEntrySerializer(serializers.ModelSerializer):
    """Сериализатор записи механического учёта."""

    expense_name = serializers.CharField(source='expense.name', read_only=True)
    expense_unit = serializers.CharField(source='expense.unit', read_only=True)

    class Meta:
        model = MechanicalExpenseEntry
        fields = [
            'id',
            'expense',
            'expense_name',
            'expense_unit',
            'amount_spent',
            'comment',
        ]


class ProductionItemSerializer(serializers.ModelSerializer):
    """
    Сериализатор позиции производства.

    Поддерживает два способа ввода:
    1. quantity_produced — прямой ввод количества
    2. suzerain_amount — ввод через Сюзерена (автоматический расчёт)
    """

    product_name = serializers.CharField(source='product.name', read_only=True)
    product_price = serializers.DecimalField(
        source='product.final_price',
        max_digits=14,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = ProductionItem
        fields = [
            'id',
            'product',
            'product_name',
            'product_price',
            'quantity_produced',
            'suzerain_amount',
            'ingredient_cost',
            'overhead_cost',
            'total_cost',
            'cost_price',
            'revenue',
            'net_profit',
        ]
        read_only_fields = [
            'ingredient_cost',
            'overhead_cost',
            'total_cost',
            'cost_price',
            'revenue',
            'net_profit',
        ]

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация: либо quantity_produced, либо suzerain_amount."""
        quantity = data.get('quantity_produced')
        suzerain = data.get('suzerain_amount')

        # При обновлении берём существующие значения
        if self.instance:
            quantity = quantity if quantity is not None else self.instance.quantity_produced
            suzerain = suzerain if suzerain is not None else self.instance.suzerain_amount

        if not quantity and not suzerain:
            raise serializers.ValidationError(
                'Укажите либо quantity_produced, либо suzerain_amount.'
            )

        if quantity and suzerain and quantity > 0 and suzerain > 0:
            raise serializers.ValidationError(
                'Укажите только одно значение: quantity_produced ИЛИ suzerain_amount.'
            )

        return data

    def create(self, validated_data: Dict[str, Any]) -> ProductionItem:
        """Создание позиции с расчётом себестоимости."""
        item = super().create(validated_data)
        CostCalculator.calculate_production_item(item)
        return item

    def update(self, instance: ProductionItem, validated_data: Dict[str, Any]) -> ProductionItem:
        """Обновление позиции с пересчётом себестоимости."""
        item = super().update(instance, validated_data)
        CostCalculator.calculate_production_item(item)
        return item


class ProductionRecordSerializer(serializers.ModelSerializer):
    """Сериализатор записи производства."""

    partner_name = serializers.CharField(source='partner.get_full_name', read_only=True)
    items = ProductionItemSerializer(many=True, read_only=True)
    mechanical_entries = MechanicalExpenseEntrySerializer(many=True, read_only=True)

    # Агрегированные показатели
    total_quantity = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()
    total_revenue = serializers.SerializerMethodField()
    net_profit = serializers.SerializerMethodField()

    class Meta:
        model = ProductionRecord
        fields = [
            'id',
            'partner',
            'partner_name',
            'date',
            'items',
            'mechanical_entries',
            'total_quantity',
            'total_cost',
            'total_revenue',
            'net_profit',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_quantity(self, obj: ProductionRecord) -> Decimal:
        """Общее количество произведённой продукции."""
        return obj.get_total_quantity()

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_cost(self, obj: ProductionRecord) -> Decimal:
        """Общая себестоимость."""
        return obj.get_total_cost()

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_revenue(self, obj: ProductionRecord) -> Decimal:
        """Общая выручка."""
        return obj.get_total_revenue()

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_net_profit(self, obj: ProductionRecord) -> Decimal:
        """Чистая прибыль."""
        return obj.get_net_profit()


# =============================================================================
# BONUS SERIALIZERS
# =============================================================================

class BonusHistorySerializer(serializers.ModelSerializer):
    """Сериализатор истории бонусов."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    partner_name = serializers.SerializerMethodField()
    order_id = serializers.IntegerField(source='order.id', read_only=True, allow_null=True)

    class Meta:
        model = BonusHistory
        fields = [
            'id',
            'store',
            'store_name',
            'partner',
            'partner_name',
            'product',
            'product_name',
            'order_id',
            'quantity',
            'bonus_value',
            'created_at',
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_partner_name(self, obj: BonusHistory) -> str:
        """Имя партнёра."""
        if obj.partner:
            return obj.partner.get_full_name() or obj.partner.email
        return ''


class BonusStatusSerializer(serializers.Serializer):
    """Сериализатор статуса бонуса для товара."""

    total_count = serializers.IntegerField()
    bonuses_given = serializers.IntegerField()
    pending_bonuses = serializers.IntegerField()
    next_bonus_at = serializers.IntegerField()
    has_bonus = serializers.BooleanField()
    last_bonus_at = serializers.DateTimeField(allow_null=True)
    progress = serializers.IntegerField()
    progress_percent = serializers.FloatField()


class StoreProductCounterSerializer(serializers.ModelSerializer):
    """Сериализатор счётчика товаров."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    pending_bonuses = serializers.SerializerMethodField()
    has_bonus = serializers.SerializerMethodField()

    class Meta:
        model = StoreProductCounter
        fields = [
            'id',
            'store',
            'store_name',
            'partner',
            'product',
            'product_name',
            'total_count',
            'bonuses_given',
            'pending_bonuses',
            'has_bonus',
            'last_bonus_at',
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_pending_bonuses(self, obj: StoreProductCounter) -> int:
        """Количество невыданных бонусов."""
        return obj.get_pending_bonus_count()

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_has_bonus(self, obj: StoreProductCounter) -> bool:
        """Есть ли доступный бонус."""
        return obj.has_pending_bonus()


# =============================================================================
# DEFECTIVE PRODUCT SERIALIZERS
# =============================================================================

class DefectiveProductSerializer(serializers.ModelSerializer):
    """Сериализатор бракованного товара."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    partner_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DefectiveProduct
        fields = [
            'id',
            'product',
            'product_name',
            'partner',
            'partner_name',
            'quantity',
            'reason',
            'status',
            'status_display',
            'created_at',
            'resolved_at',
        ]
        read_only_fields = ['partner', 'created_at', 'resolved_at']

    @extend_schema_field(OpenApiTypes.STR)
    def get_partner_name(self, obj: DefectiveProduct) -> str:
        """Имя партнёра."""
        if obj.partner:
            return obj.partner.get_full_name() or obj.partner.email
        return ''


class DefectiveProductCreateSerializer(DefectiveProductSerializer):
    """Сериализатор для создания записи о браке."""

    class Meta(DefectiveProductSerializer.Meta):
        read_only_fields = ['partner', 'status', 'created_at', 'resolved_at']


# =============================================================================
# LEGACY SERIALIZERS (для обратной совместимости)
# =============================================================================

class ProductExpenseRelationSerializer(serializers.ModelSerializer):
    """
    Сериализатор связи товара с расходом (legacy).

    DEPRECATED: Использовать RecipeSerializer.
    """

    expense_name = serializers.CharField(source='expense.name', read_only=True)
    expense_unit = serializers.CharField(source='expense.unit', read_only=True)

    class Meta:
        model = ProductExpenseRelation
        fields = [
            'id',
            'expense',
            'expense_name',
            'expense_unit',
            'proportion',
        ]


# =============================================================================
# ФИНАНСОВЫЕ СЕРИАЛИЗАТОРЫ
# =============================================================================

class ProductionFinanceSummarySerializer(serializers.Serializer):
    """Агрегированный финансовый результат по производству."""

    record_id = serializers.IntegerField()
    date = serializers.DateField()

    total_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    ingredient_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    overhead_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    net_profit = serializers.DecimalField(max_digits=14, decimal_places=2)

    fixed_daily_overhead = serializers.DecimalField(max_digits=14, decimal_places=2)
    mechanical_daily_overhead = serializers.DecimalField(max_digits=14, decimal_places=2)

    cost_per_unit = serializers.DecimalField(max_digits=14, decimal_places=4)
    profit_per_unit = serializers.DecimalField(max_digits=14, decimal_places=4)
