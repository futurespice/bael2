# apps/products/serializers.py - ПОЛНАЯ ВЕРСИЯ v3.0
"""
Сериализаторы для products (на основе правильной архитектуры).

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v3.0:
1. ExpenseSerializer - поддержка физических + накладных
2. ProductRecipeSerializer - связь товаров с расходами
3. ProductionCalculateSerializer - два сценария расчёта
4. Удалены сериализаторы для Ingredient (модель убрана)
"""

from rest_framework import serializers
from decimal import Decimal
from datetime import date

from .models import (
    Expense,
    ExpenseType,
    ExpenseStatus,
    Product,
    ProductRecipe,
    ProductionBatch,
    ProductImage,
    ProductExpenseRelation,
    PartnerExpense,
)


# =============================================================================
# EXPENSE SERIALIZERS
# =============================================================================

class ExpenseSerializer(serializers.ModelSerializer):
    """
    Сериализатор расхода (физический или накладной).

    ПРИМЕРЫ:
    - Физический: Лук, Мука, Фарш (с price_per_unit)
    - Накладной: Аренда, Зарплата (с monthly_amount, daily_amount)
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
            'unit_type',
            'unit_type_display',
            'price_per_unit',
            'depends_on_suzerain',
            'dependency_ratio',
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
            'unit_type',
            'price_per_unit',
            'depends_on_suzerain',
            'dependency_ratio',
            'monthly_amount',
            'daily_amount',
            'description'
        ]

    def validate(self, attrs):
        """Валидация полей."""
        expense_type = attrs.get('expense_type')

        # Физические должны иметь unit_type и price_per_unit
        if expense_type == ExpenseType.PHYSICAL:
            if not attrs.get('unit_type'):
                raise serializers.ValidationError({
                    'unit_type': 'Физический расход должен иметь тип учёта'
                })
            if not attrs.get('price_per_unit') or attrs.get('price_per_unit') <= 0:
                raise serializers.ValidationError({
                    'price_per_unit': 'Физический расход должен иметь цену за единицу'
                })

        # Вассал должен зависеть от Сюзерена
        if attrs.get('expense_status') == ExpenseStatus.VASSAL:
            if not attrs.get('depends_on_suzerain'):
                raise serializers.ValidationError({
                    'depends_on_suzerain': 'Вассал должен зависеть от Сюзерена'
                })
            if not attrs.get('dependency_ratio'):
                raise serializers.ValidationError({
                    'dependency_ratio': 'Вассал должен иметь коэффициент зависимости'
                })

        return attrs


class ExpenseListSerializer(serializers.ModelSerializer):
    """Краткий список расходов."""

    expense_type_display = serializers.CharField(source='get_expense_type_display', read_only=True)
    expense_status_display = serializers.CharField(source='get_expense_status_display', read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id',
            'name',
            'expense_type',
            'expense_type_display',
            'expense_status',
            'expense_status_display',
            'price_per_unit',
            'monthly_amount',
            'daily_amount',
            'is_active'
        ]


# =============================================================================
# PRODUCT RECIPE SERIALIZERS
# =============================================================================

class ProductRecipeSerializer(serializers.ModelSerializer):
    """
    Сериализатор рецепта товара.

    ПРИМЕР:
    {
        "product": 1,
        "expense": 2,
        "quantity_per_unit": 0.01,  // для Сюзерена
        "proportion": 0.5            // для остальных
    }
    """

    product_name = serializers.CharField(source='product.name', read_only=True)
    expense_name = serializers.CharField(source='expense.name', read_only=True)
    expense_type = serializers.CharField(source='expense.expense_type', read_only=True)
    expense_status = serializers.CharField(source='expense.expense_status', read_only=True)

    class Meta:
        model = ProductRecipe
        fields = [
            'id',
            'product',
            'product_name',
            'expense',
            'expense_name',
            'expense_type',
            'expense_status',
            'quantity_per_unit',
            'proportion',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ProductRecipeCreateSerializer(serializers.ModelSerializer):
    """Создание рецепта."""

    class Meta:
        model = ProductRecipe
        fields = ['product', 'expense', 'quantity_per_unit', 'proportion']

    def validate(self, attrs):
        """Валидация."""
        expense = attrs.get('expense')

        # Сюзерен должен иметь quantity_per_unit
        if expense.expense_status == ExpenseStatus.SUZERAIN:
            if not attrs.get('quantity_per_unit'):
                raise serializers.ValidationError({
                    'quantity_per_unit': 'Сюзерен должен иметь quantity_per_unit'
                })
        else:
            # Остальные должны иметь proportion (кроме универсальных)
            if expense.apply_type != 'universal' and not attrs.get('proportion'):
                raise serializers.ValidationError({
                    'proportion': 'Расход должен иметь пропорцию'
                })

        return attrs


# =============================================================================
# PRODUCT SERIALIZERS
# =============================================================================

class ProductImageSerializer(serializers.ModelSerializer):
    """Сериализатор изображения."""

    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']


class ProductListSerializer(serializers.ModelSerializer):
    """Список товаров (для партнёров и магазинов)."""

    images = serializers.SerializerMethodField()
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)

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
            'images'
        ]

    def get_images(self, obj):
        return [
            {
                'id': img.id,
                'image': img.image.url if img.image else None,
                'order': img.order
            }
            for img in obj.images.all()[:3]
        ]


class ProductDetailSerializer(serializers.ModelSerializer):
    """Детальная информация о товаре (для админа)."""

    images = serializers.SerializerMethodField()
    recipe_items = ProductRecipeSerializer(many=True, read_only=True)
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)
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
            'manual_price',
            'final_price',
            'price_per_100g',
            'profit',
            'stock_quantity',
            'is_active',
            'is_available',
            'popularity_weight',
            'images',
            'recipe_items',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id', 'average_cost_price', 'final_price',
            'price_per_100g', 'profit', 'created_at', 'updated_at'
        ]

    def get_images(self, obj):
        return [
            {
                'id': img.id,
                'image': img.image.url if img.image else None,
                'order': img.order
            }
            for img in obj.images.all()
        ]


class ProductCreateSerializer(serializers.ModelSerializer):
    """Создание товара."""

    images = serializers.ListField(
        child=serializers.ImageField(),
        max_length=3,
        required=False,
        write_only=True
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
            'manual_price',
            'stock_quantity',
            'popularity_weight',
            'images'
        ]

    def validate_name(self, value):
        """Проверка уникальности."""
        if Product.objects.filter(name__iexact=value.strip()).exists():
            raise serializers.ValidationError(
                f'Товар с названием "{value}" уже существует'
            )
        return value.strip()

    def validate(self, attrs):
        """Валидация."""
        # Весовые товары должны быть в кг
        if attrs.get('is_weight_based') and attrs.get('unit') != 'kg':
            raise serializers.ValidationError({
                'unit': 'Весовые товары должны быть в кг'
            })

        # Весовые товары не могут быть бонусными
        if attrs.get('is_weight_based') and attrs.get('is_bonus'):
            raise serializers.ValidationError({
                'is_bonus': 'Весовые товары не могут быть бонусными'
            })

        return attrs

    def create(self, validated_data):
        """Создание товара с изображениями."""
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


# =============================================================================
# PRODUCTION BATCH SERIALIZERS
# =============================================================================

class ProductionBatchSerializer(serializers.ModelSerializer):
    """Сериализатор производственной партии."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    input_type_display = serializers.CharField(source='get_input_type_display', read_only=True)

    class Meta:
        model = ProductionBatch
        fields = [
            'id',
            'product',
            'product_name',
            'date',
            'quantity_produced',
            'total_physical_cost',
            'total_overhead_cost',
            'cost_per_unit',
            'input_type',
            'input_type_display',
            'notes',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id', 'total_physical_cost', 'total_overhead_cost',
            'cost_per_unit', 'created_at', 'updated_at'
        ]


class ProductionCalculateSerializer(serializers.Serializer):
    """
    Расчёт производства (два сценария).

    СЦЕНАРИЙ 1: От количества товара
    {
        "input_type": "quantity",
        "quantity": 200
    }

    СЦЕНАРИЙ 2: От объёма Сюзерена
    {
        "input_type": "suzerain",
        "suzerain_quantity": 2.0
    }
    """

    input_type = serializers.ChoiceField(
        choices=['quantity', 'suzerain'],
        help_text='Тип ввода: quantity (от количества) или suzerain (от Сюзерена)'
    )

    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        min_value=Decimal('0.01'),
        help_text='Количество товара (для input_type=quantity)'
    )

    suzerain_quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        min_value=Decimal('0.01'),
        help_text='Количество Сюзерена в кг/шт (для input_type=suzerain)'
    )

    def validate(self, attrs):
        """Валидация."""
        input_type = attrs.get('input_type')

        if input_type == 'quantity':
            if not attrs.get('quantity'):
                raise serializers.ValidationError({
                    'quantity': 'Укажите quantity для input_type=quantity'
                })
        elif input_type == 'suzerain':
            if not attrs.get('suzerain_quantity'):
                raise serializers.ValidationError({
                    'suzerain_quantity': 'Укажите suzerain_quantity для input_type=suzerain'
                })

        return attrs


class ProductionBatchCreateSerializer(serializers.Serializer):
    """
    Создание производственной партии.

    ПРИМЕР:
    {
        "input_type": "quantity",
        "quantity": 200,
        "date": "2026-01-02",
        "notes": "Производство пельменей"
    }
    """

    input_type = serializers.ChoiceField(choices=['quantity', 'suzerain'])
    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        min_value=Decimal('0.01')
    )
    suzerain_quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        min_value=Decimal('0.01')
    )
    date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        """Валидация."""
        input_type = attrs.get('input_type')

        if input_type == 'quantity' and not attrs.get('quantity'):
            raise serializers.ValidationError({
                'quantity': 'Укажите quantity'
            })

        if input_type == 'suzerain' and not attrs.get('suzerain_quantity'):
            raise serializers.ValidationError({
                'suzerain_quantity': 'Укажите suzerain_quantity'
            })

        return attrs


# =============================================================================
# PARTNER EXPENSE SERIALIZERS
# =============================================================================

class PartnerExpenseCreateSerializer(serializers.ModelSerializer):
    """Создание расхода партнёра."""

    class Meta:
        model = PartnerExpense
        fields = ['amount', 'description', 'date']

    def validate_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError('Сумма должна быть больше 0')
        return value


class PartnerExpenseListSerializer(serializers.ModelSerializer):
    """Список расходов партнёра."""

    class Meta:
        model = PartnerExpense
        fields = ['id', 'amount', 'description', 'date', 'created_at']
        read_only_fields = fields


# =============================================================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ
# =============================================================================

class ProductExpenseRelationSerializer(serializers.ModelSerializer):
    """
    УСТАРЕЛО! Для обратной совместимости.
    Используйте ProductRecipeSerializer вместо этого.
    """

    product_name = serializers.CharField(source='product.name', read_only=True)
    expense_name = serializers.CharField(source='expense.name', read_only=True)

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