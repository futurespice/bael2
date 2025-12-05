# apps/products/serializers.py
"""Сериализаторы для products."""

from rest_framework import serializers
from decimal import Decimal
from .models import (
    Expense,
    Product,
    ProductionBatch,
    ProductImage,
    ProductExpenseRelation
)


# =============================================================================
# EXPENSE SERIALIZERS
# =============================================================================

class ExpenseSerializer(serializers.ModelSerializer):
    """Сериализатор расхода."""

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
    """Создание расхода."""

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
    """Создание товара."""

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
            'popularity_weight'
        ]

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