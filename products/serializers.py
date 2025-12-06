# apps/products/serializers.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Сериализаторы для products.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. Добавлены сериализаторы для PartnerExpense
2. Добавлен сериализатор для ProductExpenseRelation CRUD
3. Добавлен сериализатор для расчёта себестоимости
"""

from rest_framework import serializers
from decimal import Decimal
from .models import (
    Expense,
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
    """Сериализатор расхода на производство."""

    expense_type_display = serializers.CharField(
        source='get_expense_type_display',
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
            'expense_state',
            'apply_type',
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
            'monthly_amount',
            'daily_amount',
            'description'
        ]

    def validate(self, attrs):
        if attrs.get('monthly_amount', 0) == 0 and attrs.get('daily_amount', 0) == 0:
            raise serializers.ValidationError(
                'Укажите месячную или дневную сумму'
            )
        return attrs


# =============================================================================
# PARTNER EXPENSE SERIALIZERS (НОВОЕ v2.0)
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
    """
    Создание расхода партнёра.
    
    Партнёр указывает только amount и description.
    partner берётся из request.user.
    """

    class Meta:
        model = PartnerExpense
        fields = ['amount', 'description', 'date']

    def validate_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError('Сумма расхода должна быть больше 0')
        return value

    def validate_description(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('Описание расхода обязательно')
        return value.strip()


class PartnerExpenseListSerializer(serializers.ModelSerializer):
    """Сериализатор списка расходов партнёра."""

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
            'created_at'
        ]
        read_only_fields = ['id', 'partner', 'created_at']


# =============================================================================
# PRODUCTION SERIALIZERS
# =============================================================================

class ProductionBatchSerializer(serializers.ModelSerializer):
    """Производственная партия."""

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
        read_only_fields = [
            'id',
            'total_daily_expenses',
            'total_monthly_expenses_per_day',
            'cost_price_calculated',
            'created_at'
        ]


class ProductionBatchCreateSerializer(serializers.Serializer):
    """Создание производственной записи."""

    product_id = serializers.IntegerField()
    date = serializers.DateField()
    quantity_produced = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01')
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500
    )


# =============================================================================
# PRODUCT IMAGE SERIALIZERS
# =============================================================================

class ProductImageSerializer(serializers.ModelSerializer):
    """Изображение товара."""

    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']


# =============================================================================
# PRODUCT SERIALIZERS
# =============================================================================

class ProductListSerializer(serializers.ModelSerializer):
    """Список товаров."""

    unit_display = serializers.CharField(
        source='get_unit_display',
        read_only=True
    )

    main_image = serializers.SerializerMethodField()

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
            'main_image',
        ]

    def get_main_image(self, obj):
        main = obj.images.filter(order=0).first()
        if main:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(main.image.url)
        return None


class ProductDetailSerializer(serializers.ModelSerializer):
    """Детали товара."""

    unit_display = serializers.CharField(
        source='get_unit_display',
        read_only=True
    )

    profit_per_unit = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )

    images = ProductImageSerializer(many=True, read_only=True)

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
            'final_price',
            'profit_per_unit',
            'price_per_100g',
            'stock_quantity',
            'is_active',
            'is_available',
            'popularity_weight',
            'images',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'average_cost_price',
            'final_price',
            'profit_per_unit',
            'price_per_100g',
            'created_at',
            'updated_at'
        ]


class ProductCreateSerializer(serializers.ModelSerializer):
    """Создание товара с возможностью загрузки изображений."""
    
    images = serializers.ListField(
        child=serializers.ImageField(),
        max_length=3,
        required=False,
        write_only=True,
        help_text='До 3 изображений'
    )
    
    # ✅ ИСПРАВЛЕНИЕ: Явная валидация описания (ТЗ v2.0: до 250 символов)
    description = serializers.CharField(
        max_length=250,
        required=False,
        allow_blank=True,
        help_text='Описание товара (до 250 символов)'
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
            'stock_quantity',
            'popularity_weight',
            'images'
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
        if attrs.get('is_weight_based') and attrs.get('unit') != 'kg':
            raise serializers.ValidationError({
                'unit': 'Весовые товары должны быть в кг'
            })

        if attrs.get('is_weight_based') and attrs.get('is_bonus'):
            raise serializers.ValidationError({
                'is_bonus': 'Весовые не могут быть бонусными'
            })

        return attrs
    
    def create(self, validated_data):
        images_data = validated_data.pop('images', [])
        product = Product.objects.create(**validated_data)
        
        # Создаём изображения
        for i, image in enumerate(images_data[:3]):
            ProductImage.objects.create(
                product=product,
                image=image,
                order=i
            )
        
        return product


class ProductUpdateMarkupSerializer(serializers.Serializer):
    """Обновление наценки."""

    markup_percentage = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal('0'),
        max_value=Decimal('1000')
    )


# =============================================================================
# PRODUCT EXPENSE RELATION SERIALIZERS
# =============================================================================

class ProductExpenseRelationSerializer(serializers.ModelSerializer):
    """Связь товар-расход."""

    expense_name = serializers.CharField(source='expense.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = ProductExpenseRelation
        fields = [
            'id',
            'product',
            'product_name',
            'expense',
            'expense_name',
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
        # Проверка на дубликат
        if ProductExpenseRelation.objects.filter(
            product=attrs['product'],
            expense=attrs['expense']
        ).exists():
            raise serializers.ValidationError(
                'Связь между этим товаром и расходом уже существует'
            )
        return attrs


# =============================================================================
# COST CALCULATION SERIALIZERS (НОВОЕ v2.0)
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
        help_text='Дата для расчёта расходов (по умолчанию - сегодня)'
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


# =============================================================================
# SUMMARY SERIALIZERS
# =============================================================================

class ExpenseSummarySerializer(serializers.Serializer):
    """Сводка по расходам."""

    total_daily = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_monthly = serializers.DecimalField(max_digits=14, decimal_places=2)
    monthly_per_day = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_per_day = serializers.DecimalField(max_digits=14, decimal_places=2)
    expenses_count = serializers.IntegerField()
    physical_count = serializers.IntegerField()
    overhead_count = serializers.IntegerField()


class PartnerExpenseSummarySerializer(serializers.Serializer):
    """Сводка по расходам партнёров."""
    
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    expenses_count = serializers.IntegerField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
