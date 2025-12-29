# apps/products/serializers.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.1
"""
Сериализаторы для products.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.1:
1. ExpenseSerializer - добавлен unit_type
2. ProductCreateSerializer - добавлен expense_ids для привязки расходов
3. ProductAdminDetailSerializer - добавлен manual_price
"""

from rest_framework import serializers
from decimal import Decimal
from .models import (
    Expense,
    ExpenseUnitType,
    PartnerExpense,
    Product,
    ProductionBatch,
    ProductImage,
    ProductExpenseRelation
)


# =============================================================================
# EXPENSE SERIALIZERS (PRODUCTION)
# =============================================================================

class ExpenseSerializer(serializers.ModelSerializer):
    """
    Сериализатор расхода на производство.

    ✅ ИЗМЕНЕНО v2.1: Добавлен unit_type
    """

    expense_type_display = serializers.CharField(
        source='get_expense_type_display',
        read_only=True
    )
    expense_status_display = serializers.CharField(
        source='get_expense_status_display',
        read_only=True
    )
    expense_state_display = serializers.CharField(
        source='get_expense_state_display',
        read_only=True
    )
    apply_type_display = serializers.CharField(
        source='get_apply_type_display',
        read_only=True
    )
    # ✅ НОВОЕ v2.1
    unit_type_display = serializers.CharField(
        source='get_unit_type_display',
        read_only=True
    )

    class Meta:
        model = Expense
        fields = [
            'id',
            'name',
            'expense_type',
            'expense_type_display',
            'expense_status',
            'expense_status_display',
            'expense_state',
            'expense_state_display',
            'apply_type',
            'apply_type_display',
            'unit_type',  # ✅ НОВОЕ v2.1
            'unit_type_display',  # ✅ НОВОЕ v2.1
            'depends_on_suzerain',
            'dependency_ratio',
            'quantity',
            'unit_cost',
            'monthly_amount',
            'daily_amount',
            'description',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ExpenseCreateSerializer(serializers.ModelSerializer):
    """Создание расхода на производство."""

    class Meta:
        model = Expense
        fields = [
            'name',
            'expense_type',
            'expense_status',
            'expense_state',
            'apply_type',
            'unit_type',  # ✅ НОВОЕ v2.1
            'depends_on_suzerain',
            'dependency_ratio',
            'quantity',
            'unit_cost',
            'monthly_amount',
            'daily_amount',
            'description'
        ]

    def validate(self, attrs):
        # Валидация: должна быть указана хотя бы одна сумма
        monthly = attrs.get('monthly_amount', 0) or 0
        daily = attrs.get('daily_amount', 0) or 0
        unit_cost = attrs.get('unit_cost', 0) or 0

        if monthly == 0 and daily == 0 and unit_cost == 0:
            raise serializers.ValidationError(
                'Укажите месячную, дневную сумму или цену за единицу'
            )

        # Валидация Вассалов
        status = attrs.get('expense_status')
        if status == 'vassal':
            if not attrs.get('depends_on_suzerain'):
                raise serializers.ValidationError({
                    'depends_on_suzerain': 'Вассал должен зависеть от Сюзерена'
                })
            if not attrs.get('dependency_ratio'):
                raise serializers.ValidationError({
                    'dependency_ratio': 'Укажите коэффициент зависимости'
                })

        return attrs


class ExpenseSummarySerializer(serializers.Serializer):
    """Сводка по расходам."""

    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    expenses_count = serializers.IntegerField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()


# =============================================================================
# PARTNER EXPENSE SERIALIZERS (v2.0)
# =============================================================================

class PartnerExpenseSerializer(serializers.ModelSerializer):
    """
    Сериализатор расхода партнёра.

    ТЗ: "Партнер добавляет расходы: Amount + Description"
    """

    partner_name = serializers.CharField(
        source='partner.get_full_name',
        read_only=True
    )

    class Meta:
        model = PartnerExpense
        fields = [
            'id',
            'partner',
            'partner_name',
            'amount',
            'description',
            'date',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'partner', 'created_at', 'updated_at']


class PartnerExpenseCreateSerializer(serializers.ModelSerializer):
    """Создание расхода партнёра."""

    class Meta:
        model = PartnerExpense
        fields = ['amount', 'description', 'date']

    def validate_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError('Сумма должна быть больше 0')
        return value

    def validate_description(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('Описание обязательно')
        return value.strip()


class PartnerExpenseListSerializer(serializers.ModelSerializer):
    """Список расходов партнёра (краткая версия)."""

    class Meta:
        model = PartnerExpense
        fields = ['id', 'amount', 'description', 'date', 'created_at']
        read_only_fields = fields


class PartnerExpenseSummarySerializer(serializers.Serializer):
    """Сводка расходов партнёра."""

    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    expenses_count = serializers.IntegerField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()


# =============================================================================
# PRODUCT IMAGE SERIALIZERS
# =============================================================================

class ProductImageSerializer(serializers.ModelSerializer):
    """Сериализатор изображения товара."""

    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']


# =============================================================================
# PRODUCT SERIALIZERS (ДЛЯ ПАРТНЁРОВ И МАГАЗИНОВ)
# =============================================================================

class ProductListSerializer(serializers.ModelSerializer):
    """
    Список товаров для партнёров и магазинов.

    СКРЫТО:
    - average_cost_price (себестоимость)
    - markup_percentage (процент наценки)
    - manual_price (ручная цена)
    - profit_per_unit (прибыль с единицы)

    ВИДНО:
    - final_price (финальная цена продажи)
    """

    images = serializers.SerializerMethodField()
    unit_display = serializers.CharField(
        source='get_unit_display',
        read_only=True
    )

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'description',
            'unit',
            'unit_display',
            'is_weight_based',
            'is_bonus',
            'final_price',
            'price_per_100g',
            'stock_quantity',
            'is_active',
            'is_available',
            'images',
        ]
        read_only_fields = fields

    def get_images(self, obj):
        """Получить список изображений."""
        return [
            {
                'id': img.id,
                'image': img.image.url if img.image else None,
                'order': img.order
            }
            for img in obj.images.all()[:3]
        ]


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Детальная информация о товаре для партнёров и магазинов.

    СКРЫТО:
    - average_cost_price, markup_percentage, manual_price, profit_per_unit
    """

    images = serializers.SerializerMethodField()
    unit_display = serializers.CharField(
        source='get_unit_display',
        read_only=True
    )

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'description',
            'unit',
            'unit_display',
            'is_weight_based',
            'is_bonus',
            'final_price',
            'price_per_100g',
            'stock_quantity',
            'is_active',
            'is_available',
            'popularity_weight',
            'images',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_images(self, obj):
        """Получить список изображений."""
        return [
            {
                'id': img.id,
                'image': img.image.url if img.image else None,
                'order': img.order
            }
            for img in obj.images.all()
        ]


# =============================================================================
# PRODUCT SERIALIZERS (ДЛЯ АДМИНИСТРАТОРА)
# =============================================================================

class ProductAdminListSerializer(serializers.ModelSerializer):
    """
    Список товаров для администратора (с себестоимостью и наценкой).

    ✅ ИЗМЕНЕНО v2.1: Добавлен manual_price
    """

    images = serializers.SerializerMethodField()
    unit_display = serializers.CharField(
        source='get_unit_display',
        read_only=True
    )
    profit = serializers.DecimalField(
        source='profit_per_unit',
        max_digits=12,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'description',
            'unit',
            'unit_display',
            'is_weight_based',
            'is_bonus',
            'average_cost_price',
            'markup_percentage',
            'manual_price',  # ✅ НОВОЕ v2.1
            'final_price',
            'price_per_100g',
            'profit',
            'stock_quantity',
            'is_active',
            'is_available',
            'images',
        ]
        read_only_fields = [
            'id', 'average_cost_price', 'final_price',
            'price_per_100g', 'profit'
        ]

    def get_images(self, obj):
        """Получить список изображений."""
        return [
            {
                'id': img.id,
                'image': img.image.url if img.image else None,
                'order': img.order
            }
            for img in obj.images.all()[:3]
        ]


class ProductAdminDetailSerializer(serializers.ModelSerializer):
    """
    Детальная информация о товаре для администратора (полная).

    ✅ ИЗМЕНЕНО v2.1: Добавлен manual_price, expense_relations
    """

    images = serializers.SerializerMethodField()
    unit_display = serializers.CharField(
        source='get_unit_display',
        read_only=True
    )
    profit = serializers.DecimalField(
        source='profit_per_unit',
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    expense_relations = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'description',
            'unit',
            'unit_display',
            'is_weight_based',
            'is_bonus',
            'average_cost_price',
            'markup_percentage',
            'manual_price',  # ✅ НОВОЕ v2.1
            'final_price',
            'price_per_100g',
            'profit',
            'stock_quantity',
            'is_active',
            'is_available',
            'popularity_weight',
            'images',
            'expense_relations',  # ✅ НОВОЕ v2.1
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'average_cost_price', 'final_price',
            'price_per_100g', 'profit', 'created_at', 'updated_at'
        ]

    def get_images(self, obj):
        """Получить список изображений."""
        return [
            {
                'id': img.id,
                'image': img.image.url if img.image else None,
                'order': img.order
            }
            for img in obj.images.all()
        ]

    def get_expense_relations(self, obj):
        """Получить связанные расходы."""
        return [
            {
                'expense_id': rel.expense_id,
                'expense_name': rel.expense.name,
                'expense_type': rel.expense.expense_type,
                'proportion': float(rel.proportion) if rel.proportion else None,
            }
            for rel in obj.expense_relations.select_related('expense').all()
        ]


class ProductCreateSerializer(serializers.ModelSerializer):
    """
    Создание товара с возможностью загрузки изображений и привязки расходов.

    ✅ ИЗМЕНЕНО v2.1:
    - Добавлен manual_price
    - Добавлен expense_ids для привязки расходов
    - Добавлен expense_proportions для пропорций
    """

    images = serializers.ListField(
        child=serializers.ImageField(),
        max_length=3,
        required=False,
        write_only=True,
        help_text='До 3 изображений'
    )

    # ✅ НОВОЕ v2.1: Описание с валидацией
    description = serializers.CharField(
        max_length=250,
        required=False,
        allow_blank=True,
        help_text='Описание товара (до 250 символов)'
    )

    # ✅ НОВОЕ v2.1: Ручная цена
    manual_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal('0'),
        help_text='Ручная цена (если не указана, рассчитывается автоматически)'
    )

    # ✅ НОВОЕ v2.1: Привязка расходов
    expense_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        help_text='Список ID расходов для привязки к товару'
    )

    # ✅ НОВОЕ v2.1: Пропорции расходов
    expense_proportions = serializers.DictField(
        child=serializers.DecimalField(max_digits=10, decimal_places=3),
        required=False,
        write_only=True,
        help_text='Пропорции расходов: {"expense_id": proportion}'
    )

    class Meta:
        model = Product
        fields = [
            'name',
            'description',
            'unit',
            'is_weight_based',
            'is_bonus',
            'markup_percentage',
            'manual_price',  # ✅ НОВОЕ v2.1
            'stock_quantity',
            'popularity_weight',
            'images',
            'expense_ids',  # ✅ НОВОЕ v2.1
            'expense_proportions',  # ✅ НОВОЕ v2.1
        ]

    def validate_name(self, value):
        """
        Проверка уникальности названия товара.

        ТЗ v2.0: "Нельзя добавить два товара с одинаковым названием"
        """
        if Product.objects.filter(name__iexact=value.strip()).exists():
            raise serializers.ValidationError(
                f'Товар с названием "{value}" уже существует'
            )
        return value.strip()

    def validate(self, attrs):
        # Валидация: весовые товары должны быть в кг
        if attrs.get('is_weight_based') and attrs.get('unit') != 'kg':
            raise serializers.ValidationError({
                'unit': 'Весовые товары должны быть в кг'
            })

        # Валидация: весовые товары не могут быть бонусными
        if attrs.get('is_weight_based') and attrs.get('is_bonus'):
            raise serializers.ValidationError({
                'is_bonus': 'Весовые товары не могут быть бонусными'
            })

        # Валидация expense_ids
        expense_ids = attrs.get('expense_ids', [])
        if expense_ids:
            existing_ids = set(Expense.objects.filter(
                id__in=expense_ids,
                is_active=True
            ).values_list('id', flat=True))

            invalid_ids = set(expense_ids) - existing_ids
            if invalid_ids:
                raise serializers.ValidationError({
                    'expense_ids': f'Расходы не найдены: {list(invalid_ids)}'
                })

        return attrs

    def create(self, validated_data):
        """Создание товара с изображениями и привязкой расходов."""
        # Извлекаем дополнительные данные
        images_data = validated_data.pop('images', [])
        expense_ids = validated_data.pop('expense_ids', [])
        expense_proportions = validated_data.pop('expense_proportions', {})

        # Создаём товар
        product = Product.objects.create(**validated_data)

        # Создаём изображения
        for i, image in enumerate(images_data[:3]):
            ProductImage.objects.create(
                product=product,
                image=image,
                order=i
            )

        # ✅ НОВОЕ v2.1: Создаём связи с расходами
        for expense_id in expense_ids:
            # Получаем пропорцию (если указана)
            proportion = expense_proportions.get(str(expense_id))

            ProductExpenseRelation.objects.create(
                product=product,
                expense_id=expense_id,
                proportion=proportion
            )

        return product


class ProductUpdateSerializer(serializers.ModelSerializer):
    """
    Обновление товара.

    ✅ НОВОЕ v2.1: Поддержка manual_price
    """

    class Meta:
        model = Product
        fields = [
            'name',
            'description',
            'is_bonus',
            'markup_percentage',
            'manual_price',
            'stock_quantity',
            'is_active',
            'is_available',
            'popularity_weight',
        ]

    def validate_name(self, value):
        """Проверка уникальности названия (исключая текущий товар)."""
        instance = self.instance
        if Product.objects.filter(name__iexact=value.strip()).exclude(pk=instance.pk).exists():
            raise serializers.ValidationError(
                f'Товар с названием "{value}" уже существует'
            )
        return value.strip()


class ProductUpdateMarkupSerializer(serializers.Serializer):
    """Обновление наценки."""

    markup_percentage = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal('0'),
        max_value=Decimal('1000')
    )


class ProductSetManualPriceSerializer(serializers.Serializer):
    """
    Установка ручной цены.

    ✅ НОВОЕ v2.1
    """

    manual_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0'),
        allow_null=True,
        help_text='Ручная цена. Установите null для автоматического расчёта.'
    )


# =============================================================================
# PRODUCT EXPENSE RELATION SERIALIZERS
# =============================================================================

class ProductExpenseRelationSerializer(serializers.ModelSerializer):
    """Связь товар-расход (полная информация)."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    expense_name = serializers.CharField(source='expense.name', read_only=True)
    expense_type = serializers.CharField(source='expense.expense_type', read_only=True)
    expense_unit_type = serializers.CharField(source='expense.unit_type', read_only=True)

    class Meta:
        model = ProductExpenseRelation
        fields = [
            'id',
            'product',
            'product_name',
            'expense',
            'expense_name',
            'expense_type',
            'expense_unit_type',
            'proportion',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ProductExpenseRelationCreateSerializer(serializers.ModelSerializer):
    """Создание связи товар-расход."""

    class Meta:
        model = ProductExpenseRelation
        fields = ['product', 'expense', 'proportion']

    def validate(self, attrs):
        product = attrs.get('product')
        expense = attrs.get('expense')

        # Проверка на дубликат
        if ProductExpenseRelation.objects.filter(
                product=product,
                expense=expense
        ).exists():
            raise serializers.ValidationError(
                f'Связь между товаром "{product.name}" и расходом "{expense.name}" уже существует'
            )

        return attrs


# =============================================================================
# PRODUCTION BATCH SERIALIZERS
# =============================================================================

class ProductionBatchSerializer(serializers.ModelSerializer):
    """Сериализатор производственной партии."""

    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = ProductionBatch
        fields = [
            'id',
            'product',
            'product_name',
            'date',
            'quantity_produced',
            'total_daily_expenses',
            'total_monthly_expenses_per_day',
            'cost_price_calculated',
            'notes',
            'created_at'
        ]
        read_only_fields = ['id', 'cost_price_calculated', 'created_at']


class ProductionBatchCreateSerializer(serializers.Serializer):
    """Создание производственной записи."""

    product_id = serializers.IntegerField()
    date = serializers.DateField()
    quantity_produced = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01')
    )
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_product_id(self, value):
        if not Product.objects.filter(pk=value).exists():
            raise serializers.ValidationError('Товар не найден')
        return value


# =============================================================================
# COST CALCULATION SERIALIZERS
# =============================================================================

class CostCalculationRequestSerializer(serializers.Serializer):
    """Запрос на расчёт себестоимости."""

    quantity_produced = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        help_text='Количество произведённого товара'
    )
    date = serializers.DateField(
        required=False,
        help_text='Дата для расчёта (по умолчанию - сегодня)'
    )


class CostCalculationResultSerializer(serializers.Serializer):
    """Результат расчёта себестоимости."""

    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    quantity_produced = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_daily_expenses = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_monthly_expenses_per_day = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_expenses = serializers.DecimalField(max_digits=14, decimal_places=2)
    cost_price_per_unit = serializers.DecimalField(max_digits=12, decimal_places=2)
    suggested_final_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    current_markup_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)