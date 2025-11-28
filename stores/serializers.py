# apps/stores/serializers.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
from rest_framework import serializers
from decimal import Decimal
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from .models import (
    Region, City, Store, StoreSelection,
    StoreProductRequest, StoreRequest, StoreRequestItem,
    StoreInventory, PartnerInventory, ReturnRequest, ReturnRequestItem
)
from products.models import Product


# ============= REGION & CITY =============

class CitySerializer(serializers.ModelSerializer):
    """ИСПРАВЛЕНИЕ #4: Сериализатор города"""
    region_name = serializers.CharField(source='region.name', read_only=True)

    class Meta:
        model = City
        fields = ['id', 'name', 'region', 'region_name']


class RegionSerializer(serializers.ModelSerializer):
    """ИСПРАВЛЕНИЕ #4: Сериализатор региона с городами"""
    cities = CitySerializer(many=True, read_only=True)

    class Meta:
        model = Region
        fields = ['id', 'name', 'cities']


# ============= STORE =============

class StoreSerializer(serializers.ModelSerializer):
    """Сериализатор магазина"""
    region_name = serializers.CharField(source='region.name', read_only=True)
    city_name = serializers.CharField(source='city.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.name', read_only=True)
    approval_status_display = serializers.CharField(source='get_approval_status_display', read_only=True)

    def validate(self, data):
        region = data.get('region')
        city = data.get('city')
        if region and city and city.region != region:
            raise serializers.ValidationError({'city': 'Город должен принадлежать выбранному региону.'})
        return data

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'inn', 'owner_name', 'phone',
            'region', 'region_name', 'city', 'city_name',
            'address', 'latitude', 'longitude',
            'debt', 'approval_status', 'approval_status_display',
            'is_active', 'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['debt', 'created_by', 'created_at', 'updated_at']


class StoreSelectionSerializer(serializers.ModelSerializer):
    """Сериализатор выбора магазина"""
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_inn = serializers.CharField(source='store.inn', read_only=True)
    store_is_active = serializers.BooleanField(source='store.is_active', read_only=True)
    store_approval_status = serializers.CharField(source='store.approval_status', read_only=True)

    class Meta:
        model = StoreSelection
        fields = ['id', 'store', 'store_name', 'store_inn',
                  'store_is_active', 'store_approval_status', 'selected_at']
        read_only_fields = ['selected_at']


# ============= STORE PROFILE =============

class StoreProfileSerializer(serializers.ModelSerializer):
    """
    Профиль магазина для текущего выбранного магазина.
    Полная информация + статистика.
    """
    region_name = serializers.CharField(source='region.name', read_only=True)
    city_name = serializers.CharField(source='city.name', read_only=True)
    approval_status_display = serializers.CharField(
        source='get_approval_status_display', read_only=True
    )

    # Дополнительная статистика
    total_orders = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    pending_requests_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'inn', 'owner_name', 'phone',
            'region', 'region_name', 'city', 'city_name',
            'address', 'latitude', 'longitude',
            'debt', 'approval_status', 'approval_status_display',
            'is_active', 'created_at', 'updated_at',
            # Статистика
            'total_orders', 'total_paid', 'pending_requests_count'
        ]
        read_only_fields = [
            'id', 'inn', 'debt', 'approval_status', 'is_active',
            'created_at', 'updated_at'
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_total_orders(self, obj) -> int:
        """Общее количество заказов"""
        return obj.orders.count() if hasattr(obj, 'orders') else 0

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_paid(self, obj) -> Decimal:
        """Общая сумма оплаченных заказов"""
        from django.db.models import Sum
        result = obj.orders.aggregate(total=Sum('paid_amount'))
        return result['total'] or Decimal('0')

    @extend_schema_field(OpenApiTypes.INT)
    def get_pending_requests_count(self, obj) -> int:
        """Количество товаров в wishlist"""
        return obj.product_requests.count()


class StoreProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для обновления профиля магазина.
    Разрешено редактировать: name, owner_name, phone, region, city, address.
    ИНН редактировать НЕЛЬЗЯ (по ТЗ).
    """

    class Meta:
        model = Store
        fields = [
            'name', 'owner_name', 'phone',
            'region', 'city', 'address',
            'latitude', 'longitude'
        ]

    def validate_phone(self, value):
        """Валидация телефона: только цифры в формате +996XXXXXXXXX"""
        import re
        if not re.match(r'^\+996\d{9}$', value):
            raise serializers.ValidationError(
                'Телефон должен быть в формате +996XXXXXXXXX'
            )
        return value

    def validate(self, data):
        """Проверка что город принадлежит региону"""
        region = data.get('region') or (self.instance.region if self.instance else None)
        city = data.get('city') or (self.instance.city if self.instance else None)

        if region and city and city.region != region:
            raise serializers.ValidationError({
                'city': 'Город должен принадлежать выбранному региону.'
            })
        return data


# ============= PRODUCT REQUESTS (WISHLIST) =============

class StoreProductRequestSerializer(serializers.ModelSerializer):
    """Запрос на товар (временная корзина / wishlist)"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_price = serializers.DecimalField(
        source='product.price',
        max_digits=10,
        decimal_places=2,
        read_only=True
    )
    product_unit = serializers.CharField(
        source='product.get_unit_display', read_only=True
    )
    product_is_weight_based = serializers.BooleanField(
        source='product.is_weight_based', read_only=True
    )

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total(self, obj) -> Decimal:
        """Общая стоимость"""
        return obj.quantity * obj.product.price

    total = serializers.SerializerMethodField()

    class Meta:
        model = StoreProductRequest
        fields = [
            'id', 'store', 'product', 'product_name',
            'product_price', 'product_unit', 'product_is_weight_based',
            'quantity', 'total', 'created_at'
        ]
        read_only_fields = ['store', 'created_at']


class AddToWishlistSerializer(serializers.Serializer):
    """Сериализатор для добавления товара в wishlist"""
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        min_value=Decimal('0.1')
    )

    def validate(self, data):
        product = data['product']
        quantity = data['quantity']

        # Валидация для весовых товаров
        if product.is_weight_based:
            if quantity < Decimal('0.1'):
                raise serializers.ValidationError({
                    'quantity': 'Минимальное количество для весового товара: 0.1 кг'
                })
        else:
            # Для штучных - целое число
            if quantity != int(quantity):
                raise serializers.ValidationError({
                    'quantity': 'Для штучного товара количество должно быть целым числом'
                })
            if quantity < 1:
                raise serializers.ValidationError({
                    'quantity': 'Минимальное количество: 1 шт'
                })

        return data


class RemoveFromWishlistSerializer(serializers.Serializer):
    """Сериализатор для удаления товара из wishlist"""
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())


# ============= STORE REQUESTS =============

class StoreRequestItemSerializer(serializers.ModelSerializer):
    """Позиция в запросе магазина"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unit = serializers.CharField(source='product.get_unit_display', read_only=True)

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total(self, obj) -> Decimal:
        """Общая стоимость позиции"""
        return obj.total

    total = serializers.SerializerMethodField()

    class Meta:
        model = StoreRequestItem
        fields = [
            'id', 'product', 'product_name', 'product_unit',
            'quantity', 'price', 'total', 'is_cancelled'
        ]


class StoreRequestSerializer(serializers.ModelSerializer):
    """История запросов магазина"""
    store_name = serializers.CharField(source='store.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.name', read_only=True)
    items = StoreRequestItemSerializer(many=True, read_only=True)
    items_count = serializers.SerializerMethodField()
    active_items_count = serializers.SerializerMethodField()

    class Meta:
        model = StoreRequest
        fields = [
            'id', 'store', 'store_name', 'created_by', 'created_by_name',
            'total_amount', 'note', 'items', 'items_count',
            'active_items_count', 'created_at'
        ]
        read_only_fields = ['total_amount', 'created_at']

    @extend_schema_field(OpenApiTypes.INT)
    def get_items_count(self, obj) -> int:
        return obj.items.count()

    @extend_schema_field(OpenApiTypes.INT)
    def get_active_items_count(self, obj) -> int:
        return obj.items.filter(is_cancelled=False).count()


class CreateStoreRequestSerializer(serializers.Serializer):
    """Создание запроса из wishlist с idempotency"""
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    idempotency_key = serializers.CharField(required=False, allow_null=True, max_length=100)


# ============= INVENTORY =============

class StoreInventorySerializer(serializers.ModelSerializer):
    """Инвентарь магазина"""
    store_name = serializers.CharField(source='store.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unit = serializers.CharField(source='product.get_unit_display', read_only=True)

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_price(self, obj) -> Decimal:
        """Общая стоимость"""
        return obj.total_price

    total_price = serializers.SerializerMethodField()

    class Meta:
        model = StoreInventory
        fields = [
            'id', 'store', 'store_name', 'product', 'product_name',
            'product_unit', 'quantity', 'total_price', 'last_updated'
        ]


class PartnerInventorySerializer(serializers.ModelSerializer):
    """Инвентарь партнёра"""
    partner_name = serializers.CharField(source='partner.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unit = serializers.CharField(source='product.get_unit_display', read_only=True)

    class Meta:
        model = PartnerInventory
        fields = [
            'id', 'partner', 'partner_name', 'product', 'product_name',
            'product_unit', 'quantity', 'last_updated'
        ]


# ============= RETURN REQUESTS =============

class ReturnRequestItemSerializer(serializers.ModelSerializer):
    """Позиция в возврате"""
    product_name = serializers.CharField(source='product.name', read_only=True)

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total(self, obj) -> Decimal:
        """Общая стоимость позиции"""
        return obj.total

    total = serializers.SerializerMethodField()

    class Meta:
        model = ReturnRequestItem
        fields = [
            'id', 'product', 'product_name',
            'quantity', 'price', 'total'
        ]


class ReturnRequestSerializer(serializers.ModelSerializer):
    """Запрос на возврат"""
    partner_name = serializers.CharField(source='partner.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items = ReturnRequestItemSerializer(many=True, read_only=True)

    class Meta:
        model = ReturnRequest
        fields = [
            'id', 'partner', 'partner_name',
            'status', 'status_display', 'total_amount',
            'reason', 'items', 'created_at'
        ]
        read_only_fields = ['partner', 'total_amount', 'status', 'created_at']


# ============= STORE DEBT INFO =============

class StoreDebtSerializer(serializers.ModelSerializer):
    """Информация о долге магазина"""
    total_debt = serializers.DecimalField(
        source='debt', max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = Store
        fields = ['id', 'name', 'total_debt']