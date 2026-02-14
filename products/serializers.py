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
from drf_spectacular.utils import extend_schema_field
from typing import List, Dict, Any
import re


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_indexed_fields(data, field_name):
    """
    Парсинг индексированных полей типа recipe_items[0][expense] из QueryDict.
    Возвращает список словарей.
    """
    items = {}
    pattern = re.compile(rf'^{field_name}\[(\d+)\]\[(\w+)\]$')
    
    for key, value in data.items():
        match = pattern.match(key)
        if match:
            index = int(match.group(1))
            field = match.group(2)
            if index not in items:
                items[index] = {}
            items[index][field] = value
            
    # Преобразуем в список, сортируя по индексу
    return [items[i] for i in sorted(items.keys())]


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
# ВАЛИДАЦИЯ ИЗОБРАЖЕНИЙ
# =============================================================================

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


def validate_image_size(image):
    """
    Валидация размера изображения (макс 5 МБ).
    
    ТЗ v3.0: Изображения до 5 МБ, JPG/PNG.
    """
    if image.size > MAX_IMAGE_SIZE:
        size_mb = image.size / 1024 / 1024
        raise serializers.ValidationError(
            f'Изображение слишком большое ({size_mb:.1f} МБ). Максимум 5 МБ.'
        )
    return image


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


class ProductRecipeNestedSerializer(serializers.ModelSerializer):
    """Вложенный сериализатор для создания/обновления товара (без field 'product')."""

    class Meta:
        model = ProductRecipe
        fields = ['expense', 'quantity_per_unit', 'proportion']

    def validate(self, attrs):
        """Валидация (дублирует логику ProductRecipeCreateSerializer)."""
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

    def validate_image(self, value):
        """Валидация размера изображения (макс 5 МБ)."""
        return validate_image_size(value)


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

    @extend_schema_field(serializers.ListSerializer(child=serializers.DictField()))
    def get_images(self, obj) -> List[Dict[str, Any]]:
        request = self.context.get('request')
        images = []
        for img in obj.images.all()[:3]:
            image_url = None
            preview_url = None
            if img.image:
                image_url = request.build_absolute_uri(img.image.url) if request else img.image.url
            if img.preview:
                preview_url = request.build_absolute_uri(img.preview.url) if request else img.preview.url
            images.append({
                'id': img.id,
                'image': image_url,
                'preview': preview_url or image_url,
                'order': img.order
            })
        return images


class ProductDetailSerializer(serializers.ModelSerializer):
    """Детальная информация о товаре (для админа)."""

    images_read = serializers.SerializerMethodField(source='images')
    images = serializers.ListField(
        child=serializers.ImageField(),
        max_length=3,
        required=False,
        write_only=True
    )
    recipe_items = ProductRecipeNestedSerializer(many=True, required=False, write_only=True)
    recipe_items_read = ProductRecipeSerializer(source='recipe_items', many=True, read_only=True)
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
            'images_read',
            'recipe_items',
            'recipe_items_read',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id', 'average_cost_price', 'final_price',
            'price_per_100g', 'profit', 'created_at', 'updated_at'
        ]

    @extend_schema_field(serializers.ListSerializer(child=serializers.DictField()))
    def get_images_read(self, obj) -> List[Dict[str, Any]]:
        """Возвращает список изображений для чтения."""
        request = self.context.get('request')
        images = []
        for img in obj.images.all():
            image_url = None
            preview_url = None
            if img.image:
                image_url = request.build_absolute_uri(img.image.url) if request else img.image.url
            if img.preview:
                preview_url = request.build_absolute_uri(img.preview.url) if request else img.preview.url
            images.append({
                'id': img.id,
                'image': image_url,
                'preview': preview_url or image_url,
                'order': img.order
            })
        return images

    def to_representation(self, instance):
        """Переименовываем images_read → images, recipe_items_read → recipe_items в ответе."""
        rep = super().to_representation(instance)
        if 'images_read' in rep:
            rep['images'] = rep.pop('images_read')
        if 'recipe_items_read' in rep:
            rep['recipe_items'] = rep.pop('recipe_items_read')
        return rep

    def validate_name(self, value):
        """Проверка уникальности (исключаем текущий товар)."""
        qs = Product.objects.filter(name__iexact=value.strip())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f'Товар с названием "{value}" уже существует'
            )
        return value.strip()

    def validate(self, attrs):
        """Валидация при обновлении."""
        # При PATCH поля могут отсутствовать — берём из instance
        is_weight = attrs.get(
            'is_weight_based',
            self.instance.is_weight_based if self.instance else False
        )
        unit = attrs.get(
            'unit',
            self.instance.unit if self.instance else 'piece'
        )
        is_bonus = attrs.get(
            'is_bonus',
            self.instance.is_bonus if self.instance else False
        )

        if is_weight and unit != 'kg':
            raise serializers.ValidationError({
                'unit': 'Весовые товары должны быть в кг'
            })

        if is_weight and is_bonus:
            raise serializers.ValidationError({
                'is_bonus': 'Весовые товары не могут быть бонусными'
            })

        # Запрет смены весовой → штучный (ТЗ)
        if self.instance and self.instance.is_weight_based and not is_weight:
            raise serializers.ValidationError({
                'is_weight_based': 'Запрещена смена категории "Весовой" → "Штучный"'
            })

        return attrs

    def validate_images(self, value):
        """Валидация размера изображений (макс 5 МБ)."""
        for image in value:
            validate_image_size(image)
        return value

    def to_internal_value(self, data):
        """Обработка indexed fields для recipe_items."""
        if hasattr(data, 'getlist'):
            new_data = data.dict()
            if 'images' in data:
                new_data['images'] = data.getlist('images')
        else:
            new_data = data.copy()

        # Убираем images если это не файлы (а URL строки из GET-ответа)
        images = new_data.get('images')
        if images:
            if isinstance(images, list):
                # Фильтруем: оставляем только реальные файлы
                real_files = [img for img in images if hasattr(img, 'read')]
                if real_files:
                    new_data['images'] = real_files
                else:
                    new_data.pop('images', None)
            elif isinstance(images, str):
                # Одиночная строка URL — игнорируем
                new_data.pop('images', None)

        # 1. Обработка "[]" (строка вместо пустого списка)
        if new_data.get('recipe_items') == '[]':
            new_data['recipe_items'] = []

        # 2. Обработка indexed fields: recipe_items[0][expense]
        if 'recipe_items' not in new_data:
            recipe_items = parse_indexed_fields(data, 'recipe_items')
            if recipe_items:
                new_data['recipe_items'] = recipe_items

        return super().to_internal_value(new_data)

    def update(self, instance, validated_data):
        """Обновление товара с изображениями и рецептами."""
        images_data = validated_data.pop('images', None)
        recipe_items_data = validated_data.pop('recipe_items', None)

        # Обновляем поля товара
        instance = super().update(instance, validated_data)

        # 1. ИЗОБРАЖЕНИЯ (APPEND)
        if images_data:
            # Находим следующий свободный order
            max_order = (
                instance.images.order_by('-order')
                .values_list('order', flat=True)
                .first()
            )
            next_order = (max_order + 1) if max_order is not None else 0
            current_count = instance.images.count()

            for i, image in enumerate(images_data):
                if current_count + i < 3:
                    ProductImage.objects.create(
                        product=instance,
                        image=image,
                        order=next_order + i
                    )

        # 2. РЕЦЕПТЫ (REPLACE)
        if recipe_items_data is not None:
            ProductRecipe.objects.filter(product=instance).delete()
            for item in recipe_items_data:
                ProductRecipe.objects.create(
                    product=instance,
                    **item
                )

        # Refresh для корректного ответа
        instance = Product.objects.prefetch_related(
            'images', 'recipe_items__expense'
        ).get(pk=instance.pk)

        return instance


class ProductCreateSerializer(serializers.ModelSerializer):
    """Создание товара."""

    images = serializers.ListField(
        child=serializers.ImageField(),
        max_length=3,
        required=False,
        write_only=True
    )
    recipe_items = ProductRecipeNestedSerializer(many=True, required=False)

    # Read-only поля для ответа
    images_read = serializers.SerializerMethodField(read_only=True)
    recipe_items_read = ProductRecipeSerializer(
        source='recipe_items', many=True, read_only=True
    )
    unit_display = serializers.CharField(
        source='get_unit_display', read_only=True
    )
    price_per_100g = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
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
            'markup_percentage',
            'manual_price',
            'final_price',
            'price_per_100g',
            'stock_quantity',
            'is_active',
            'is_available',
            'popularity_weight',
            'images',
            'images_read',
            'recipe_items',
            'recipe_items_read',
            'created_at',
        ]
        read_only_fields = [
            'id', 'final_price', 'price_per_100g', 'created_at'
        ]

    @extend_schema_field(serializers.ListSerializer(child=serializers.DictField()))
    def get_images_read(self, obj) -> List[Dict[str, Any]]:
        """Возвращает список изображений для ответа."""
        request = self.context.get('request')
        images = []
        for img in obj.images.all()[:3]:
            image_url = None
            preview_url = None
            if img.image:
                image_url = request.build_absolute_uri(img.image.url) if request else img.image.url
            if img.preview:
                preview_url = request.build_absolute_uri(img.preview.url) if request else img.preview.url
            images.append({
                'id': img.id,
                'image': image_url,
                'preview': preview_url or image_url,
                'order': img.order
            })
        return images

    def to_representation(self, instance):
        """Переименовываем images_read → images, recipe_items_read → recipe_items в ответе."""
        rep = super().to_representation(instance)
        if 'images_read' in rep:
            rep['images'] = rep.pop('images_read')
        if 'recipe_items_read' in rep:
            rep['recipe_items'] = rep.pop('recipe_items_read')
        return rep

    def validate_name(self, value):
        """Проверка уникальности."""
        if Product.objects.filter(name__iexact=value.strip()).exists():
            raise serializers.ValidationError(
                f'Товар с названием "{value}" уже существует'
            )
        return value.strip()

    def validate_images(self, value):
        """Валидация размера изображений (макс 5 МБ)."""
        for image in value:
            validate_image_size(image)
        return value

    def to_internal_value(self, data):
        """Обработка indexed fields для recipe_items."""
        if hasattr(data, 'getlist'):
            new_data = data.dict()
            if 'images' in data:
                new_data['images'] = data.getlist('images')
        else:
            new_data = data.copy()

        # 1. Обработка "[]"
        if new_data.get('recipe_items') == '[]':
            new_data['recipe_items'] = []

        # 2. Обработка indexed fields
        if 'recipe_items' not in new_data:
            recipe_items = parse_indexed_fields(data, 'recipe_items')
            if recipe_items:
                new_data['recipe_items'] = recipe_items

        return super().to_internal_value(new_data)

    def validate(self, attrs):
        """Валидация."""
        if attrs.get('is_weight_based') and attrs.get('unit') != 'kg':
            raise serializers.ValidationError({
                'unit': 'Весовые товары должны быть в кг'
            })

        if attrs.get('is_weight_based') and attrs.get('is_bonus'):
            raise serializers.ValidationError({
                'is_bonus': 'Весовые товары не могут быть бонусными'
            })

        return attrs

    def create(self, validated_data):
        """Создание товара с изображениями и рецептами."""
        images_data = validated_data.pop('images', [])
        recipe_items_data = validated_data.pop('recipe_items', [])

        product = Product.objects.create(**validated_data)

        # Создаём изображения
        for i, image in enumerate(images_data[:3]):
            ProductImage.objects.create(
                product=product,
                image=image,
                order=i
            )

        # Создаём рецепты
        for item in recipe_items_data:
            ProductRecipe.objects.create(
                product=product,
                **item
            )

        # Prefetch для корректного ответа
        product = Product.objects.prefetch_related(
            'images', 'recipe_items__expense'
        ).get(pk=product.pk)

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
    date = serializers.DateField(required=False, default=date.today)
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