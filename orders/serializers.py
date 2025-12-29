# apps/orders/serializers.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Сериализаторы для orders согласно ТЗ v2.0.
"""

from decimal import Decimal
from typing import Dict, Any, List

from rest_framework import serializers

from .models import (
    StoreOrder,
    StoreOrderItem,
    StoreOrderStatus,
    DebtPayment,
    DefectiveProduct,
    OrderHistory,
)


# =============================================================================
# STORE ORDER SERIALIZERS
# =============================================================================

class StoreOrderItemSerializer(serializers.ModelSerializer):
    """Сериализатор позиции заказа магазина."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unit = serializers.CharField(source='product.unit', read_only=True)
    is_weight_based = serializers.BooleanField(
        source='product.is_weight_based',
        read_only=True
    )

    class Meta:
        model = StoreOrderItem
        fields = [
            'id',
            'product',
            'product_name',
            'product_unit',
            'is_weight_based',
            'quantity',
            'price',
            'total',
            'is_bonus'
        ]
        read_only_fields = ['id', 'total']


class StoreOrderListSerializer(serializers.ModelSerializer):
    """Сериализатор заказа магазина (список)."""

    store_name = serializers.CharField(source='store.name', read_only=True)
    partner_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = StoreOrder
        fields = [
            'id',
            'store',
            'store_name',
            'partner',
            'partner_name',
            'status',
            'status_display',
            'total_amount',
            'debt_amount',
            'prepayment_amount',
            'items_count',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_partner_name(self, obj: StoreOrder) -> str:
        return obj.partner.get_full_name() if obj.partner else 'Не назначен'

    def get_items_count(self, obj: StoreOrder) -> int:
        return obj.items.count()


class StoreOrderDetailSerializer(serializers.ModelSerializer):
    """Сериализатор заказа магазина (детальный)."""

    store_name = serializers.CharField(source='store.name', read_only=True)
    store_inn = serializers.CharField(source='store.inn', read_only=True)
    partner_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    confirmed_by_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    items = StoreOrderItemSerializer(many=True, read_only=True)
    outstanding_debt = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True
    )
    is_fully_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = StoreOrder
        fields = [
            'id',
            'store',
            'store_name',
            'store_inn',
            'partner',
            'partner_name',
            'status',
            'status_display',
            'total_amount',
            'prepayment_amount',
            'debt_amount',
            'paid_amount',
            'outstanding_debt',
            'is_fully_paid',
            'reviewed_by',
            'reviewed_by_name',
            'reviewed_at',
            'confirmed_by',
            'confirmed_by_name',
            'confirmed_at',
            'items',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'status',
            'debt_amount',
            'paid_amount',
            'reviewed_by',
            'reviewed_at',
            'confirmed_by',
            'confirmed_at',
            'created_at',
            'updated_at'
        ]

    def get_partner_name(self, obj: StoreOrder) -> str:
        return obj.partner.get_full_name() if obj.partner else None

    def get_reviewed_by_name(self, obj: StoreOrder) -> str:
        return obj.reviewed_by.get_full_name() if obj.reviewed_by else None

    def get_confirmed_by_name(self, obj: StoreOrder) -> str:
        return obj.confirmed_by.get_full_name() if obj.confirmed_by else None


class StoreOrderCreateSerializer(serializers.Serializer):
    """Сериализатор создания заказа магазина."""

    items = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        help_text='Список товаров: [{"product_id": 1, "quantity": "10"}]'
    )
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64
    )

    def validate_items(self, value: List[Dict]) -> List[Dict]:
        """Валидация товаров."""
        for item in value:
            if 'product_id' not in item:
                raise serializers.ValidationError('product_id обязателен')
            if 'quantity' not in item:
                raise serializers.ValidationError('quantity обязателен')

            try:
                item['quantity'] = Decimal(str(item['quantity']))
            except:
                raise serializers.ValidationError('quantity должен быть числом')

            if item['quantity'] <= Decimal('0'):
                raise serializers.ValidationError('quantity должен быть > 0')

        return value


class OrderApproveSerializer(serializers.Serializer):
    """Одобрение заказа админом."""

    assign_to_partner_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='ID партнёра для назначения (опционально)'
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500
    )


class OrderRejectSerializer(serializers.Serializer):
    """Отклонение заказа админом."""

    reason = serializers.CharField(
        required=True,
        max_length=500,
        help_text='Причина отклонения'
    )


class OrderConfirmSerializer(serializers.Serializer):
    """Подтверждение заказа партнёром."""

    prepayment_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        min_value=Decimal('0'),
        help_text='Сумма предоплаты'
    )

    items_to_remove = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        help_text='ID продуктов для удаления из инвентаря'
    )


# =============================================================================
# DEBT PAYMENT SERIALIZERS
# =============================================================================

class DebtPaymentSerializer(serializers.ModelSerializer):
    """Сериализатор погашения долга."""

    paid_by_name = serializers.SerializerMethodField()
    received_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DebtPayment
        fields = [
            'id',
            'order',
            'amount',
            'paid_by',
            'paid_by_name',
            'received_by',
            'received_by_name',
            'comment',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_paid_by_name(self, obj: DebtPayment) -> str:
        return obj.paid_by.get_full_name() if obj.paid_by else None

    def get_received_by_name(self, obj: DebtPayment) -> str:
        return obj.received_by.get_full_name() if obj.received_by else None


class PayDebtSerializer(serializers.Serializer):
    """Погашение долга."""

    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.01'),
        help_text='Сумма погашения'
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500
    )

# =============================================================================
# ORDER HISTORY SERIALIZER
# =============================================================================

class OrderHistorySerializer(serializers.ModelSerializer):
    """Сериализатор истории заказа."""

    changed_by_name = serializers.SerializerMethodField()
    order_type_display = serializers.CharField(
        source='get_order_type_display',
        read_only=True
    )
    product_name = serializers.CharField(
        source='product.name',
        read_only=True,
        allow_null=True
    )

    class Meta:
        model = OrderHistory
        fields = [
            'id',
            'order_type',
            'order_type_display',
            'order_id',
            'product',
            'product_name',
            'old_status',
            'new_status',
            'changed_by',
            'changed_by_name',
            'comment',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_changed_by_name(self, obj: OrderHistory) -> str:
        return obj.changed_by.get_full_name() if obj.changed_by else 'Система'


class StoreOrderForStoreSerializer(serializers.ModelSerializer):
    """
    Сериализатор заказа для магазина (с полным содержимым).

    КРИТИЧЕСКИ ВАЖНО:
    - Магазин ДОЛЖЕН видеть содержимое своих заказов!
    - Включает список товаров (items) с названиями, ценами, количеством
    - Показывает статус заказа и историю изменений

    Использование:
        GET /api/orders/store-orders/my-orders/

    Response:
        {
            "id": 1,
            "store": 5,
            "store_name": "Магазин №1",
            "partner": 3,
            "partner_name": "Иван Петров",
            "status": "in_transit",
            "status_display": "В пути",
            "total_amount": "5000.00",
            "prepayment_amount": "1000.00",
            "debt_amount": "4000.00",
            "paid_amount": "2000.00",
            "outstanding_debt": "2000.00",
            "items": [  // <- ВАЖНО: Содержимое заказа!
                {
                    "id": 1,
                    "product": 10,
                    "product_name": "Манты",
                    "product_unit": "kg",
                    "is_weight_based": true,
                    "quantity": "2.500",
                    "price": "200.00",
                    "total": "500.00",
                    "is_bonus": false
                },
                {
                    "id": 2,
                    "product": 15,
                    "product_name": "Самса",
                    "product_unit": "piece",
                    "is_weight_based": false,
                    "quantity": "20.000",
                    "price": "50.00",
                    "total": "1000.00",
                    "is_bonus": false
                }
            ],
            "created_at": "2024-12-13T10:00:00Z",
            "reviewed_at": "2024-12-13T11:00:00Z",
            "confirmed_at": null
        }
    """

    # Вложенный сериализатор для товаров (используем уже существующий)
    items = serializers.SerializerMethodField()

    # Отображаемые названия
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
        help_text='Текстовое представление статуса'
    )
    store_name = serializers.CharField(
        source='store.name',
        read_only=True,
        help_text='Название магазина'
    )
    partner_name = serializers.SerializerMethodField()

    class Meta:
        model = StoreOrder
        fields = [
            'id',
            'store',
            'store_name',
            'partner',
            'partner_name',
            'status',
            'status_display',
            'total_amount',
            'prepayment_amount',
            'debt_amount',
            'paid_amount',
            'outstanding_debt',
            'items',  # ✅ КРИТИЧЕСКИ ВАЖНО: Содержимое заказа!
            'created_at',
            'reviewed_at',
            'confirmed_at',
        ]
        read_only_fields = fields

    def get_partner_name(self, obj: StoreOrder) -> str:
        """Получить имя партнёра."""
        if obj.partner:
            return obj.partner.get_full_name()
        return 'Не назначен'

    def get_items(self, obj: StoreOrder) -> list:
        """
        Получить список товаров в заказе.

        Возвращает детальную информацию о каждом товаре:
        - Название товара
        - Количество
        - Цена за единицу
        - Общая стоимость
        - Тип товара (весовой/штучный)
        - Бонусный или нет
        """
        items = obj.items.select_related('product').all()
        return [
            {
                'id': item.id,
                'product': item.product.id,
                'product_name': item.product.name,
                'product_unit': item.product.unit,
                'is_weight_based': item.product.is_weight_based,
                'quantity': str(item.quantity),
                'price': str(item.price),
                'total': str(item.total),
                'is_bonus': item.is_bonus,
            }
            for item in items
        ]