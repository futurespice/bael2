# apps/orders/serializers.py

from decimal import Decimal
from typing import Any
from django.db import transaction
from rest_framework import serializers

from products.models import Product
from stores.models import Store
from users.models import User
from .models import (
    OrderHistory,
    OrderReturn,
    OrderReturnItem,
    PartnerOrder,
    PartnerOrderItem,
    StoreOrder,
    StoreOrderItem, DebtPayment,
)
from .services import OrderService

class DebtPaymentSerializer(serializers.ModelSerializer):
    """Сериализатор истории погашения долга"""
    paid_by_name = serializers.CharField(
        source='paid_by.get_full_name', read_only=True, allow_null=True
    )
    paid_by_phone = serializers.CharField(source='paid_by.phone', read_only=True, allow_null=True)
    received_by_name = serializers.CharField(
        source='received_by.get_full_name', read_only=True, allow_null=True
    )
    received_by_phone = serializers.CharField(source='received_by.phone', read_only=True, allow_null=True)

    # Правильный вариант — просто читаемое поле, без queryset
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    order_number = serializers.CharField(source='order.id', read_only=True)  # если нужен номер заказа

    class Meta:
        model = DebtPayment
        fields = [
            'id',
            'order_id', 'order_number',
            'amount',
            'paid_by', 'paid_by_name', 'paid_by_phone',
            'received_by', 'received_by_name', 'received_by_phone',
            'comment',
            'created_at',
        ]
        read_only_fields = [
            'id', 'order_id', 'order_number',
            'paid_by', 'received_by',
            'created_at',
        ]

    def to_representation(self, instance: DebtPayment):
        ret = super().to_representation(instance)
        # Красиво форматируем сумму и дату
        ret['amount'] = f"{instance.amount:,.2f} сом"
        ret['created_at'] = instance.created_at.strftime('%d.%m.%Y %H:%M')
        return ret

class PartnerOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerOrderItem
        fields = ("id", "product", "quantity", "price", "total")
        read_only_fields = ("id", "total")


class PartnerOrderSerializer(serializers.ModelSerializer):
    items = PartnerOrderItemSerializer(many=True)
    partner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False
    )

    class Meta:
        model = PartnerOrder
        fields = (
            "id",
            "partner",
            "status",
            "total_amount",
            "comment",
            "idempotency_key",
            "created_at",
            "updated_at",
            "items",
        )
        read_only_fields = ("id", "total_amount", "created_at", "updated_at", "status")

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Нужно указать хотя бы одну позицию")
        for item in value:
            qty = item.get("quantity")
            if qty is None or Decimal(qty) <= 0:
                raise serializers.ValidationError("Количество должно быть больше 0")
        return value

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        request = self.context.get("request")
        partner = validated_data.get("partner") or getattr(request.user, "partner", None) or request.user
        created_by = request.user if request else None
        idempotency_key = validated_data.get("idempotency_key")

        products_map = {
            item["product"].id: item["product"] for item in items_data
        }
        items_payload = []
        for item in items_data:
            product: Product = item["product"]
            qty = item["quantity"]
            price = item.get("price") or product.price
            items_payload.append(
                {"product": product, "quantity": qty, "price": price}
            )

        order = OrderService.create_partner_order(
            partner=partner,
            items=items_payload,
            created_by=created_by,
            comment=validated_data.get("comment", ""),
            idempotency_key=idempotency_key,
        )
        return order


class StoreOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreOrderItem
        fields = (
            "id",
            "product",
            "quantity",
            "price",
            "total",
            "is_bonus",
        )
        read_only_fields = ("id", "total")


class StoreOrderSerializer(serializers.ModelSerializer):
    items = StoreOrderItemSerializer(many=True)
    store = serializers.PrimaryKeyRelatedField(
        queryset=Store.objects.all(), required=False
    )
    partner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False
    )
    debt_payments = DebtPaymentSerializer(many=True, read_only=True)
    outstanding_debt = serializers.SerializerMethodField()

    class Meta:
        model = StoreOrder
        fields = (
            "id",
            "store",
            "partner",
            "store_request",
            "status",
            "total_amount",
            "debt_amount",
            "paid_amount",
            "idempotency_key",
            "created_at",
            "updated_at",
            "items",
            'debt_amount', 'paid_amount', 'outstanding_debt',
            'debt_payments'
        )
        read_only_fields = (
            "id",
            "total_amount",
            "created_at",
            "updated_at",
            "status",
        )

    def get_outstanding_debt(self, obj: StoreOrder) -> str:
        return f"{obj.outstanding_debt:,.2f} сом"

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Нужно указать хотя бы одну позицию")
        for item in value:
            qty = item.get("quantity")
            if qty is None or Decimal(qty) <= 0:
                raise serializers.ValidationError("Количество должно быть больше 0")
        return value

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        request = self.context.get("request")
        store = validated_data.get("store")
        partner = validated_data.get("partner")
        if request:
            user = request.user
            if getattr(user, "role", None) == "store" and store is None:
                # магазин берём из StoreSelection, если нужно — можно доработать
                from stores.models import StoreSelection

                selection = (
                    StoreSelection.objects.filter(user=user)
                    .select_related("store")
                    .first()
                )
                if not selection:
                    raise serializers.ValidationError(
                        "У пользователя не выбран активный магазин"
                    )
                store = selection.store
            if getattr(user, "role", None) == "partner" and partner is None:
                partner = user

        created_by = request.user if request else None
        idempotency_key = validated_data.get("idempotency_key")

        items_payload = []
        for item in items_data:
            product: Product = item["product"]
            qty = item["quantity"]
            price = item.get("price") or product.price
            is_bonus = item.get("is_bonus", False)
            items_payload.append(
                {
                    "product": product,
                    "quantity": qty,
                    "price": price,
                    "is_bonus": is_bonus,
                }
            )

        order = OrderService.create_store_order(
            store=store,
            partner=partner,
            items=items_payload,
            created_by=created_by,
            store_request=validated_data.get("store_request"),
            idempotency_key=idempotency_key,
            debt_amount=validated_data.get("debt_amount", Decimal("0")),
            paid_amount=validated_data.get("paid_amount", Decimal("0")),
        )
        return order


class OrderReturnItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderReturnItem
        fields = (
            "id",
            "product",
            "quantity",
            "price",
            "total",
            "reason",
        )
        read_only_fields = ("id", "total")


class OrderReturnSerializer(serializers.ModelSerializer):
    items = OrderReturnItemSerializer(many=True)
    store = serializers.PrimaryKeyRelatedField(
        queryset=Store.objects.all(), required=False
    )
    partner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False
    )

    class Meta:
        model = OrderReturn
        fields = (
            "id",
            "store",
            "partner",
            "order",
            "status",
            "total_amount",
            "reason",
            "idempotency_key",
            "created_at",
            "updated_at",
            "items",
        )
        read_only_fields = ("id", "total_amount", "created_at", "updated_at", "status")

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        request = self.context.get("request")
        store = validated_data.get("store")
        partner = validated_data.get("partner")
        if request:
            user = request.user
            if getattr(user, "role", None) == "store" and store is None:
                from stores.models import StoreSelection

                selection = (
                    StoreSelection.objects.filter(user=user)
                    .select_related("store")
                    .first()
                )
                if not selection:
                    raise serializers.ValidationError(
                        "У пользователя не выбран активный магазин"
                    )
                store = selection.store
            if getattr(user, "role", None) == "partner" and partner is None:
                partner = user

        created_by = request.user if request else None
        idempotency_key = validated_data.get("idempotency_key")

        items_payload = []
        for item in items_data:
            product: Product = item["product"]
            qty = item["quantity"]
            price = item.get("price") or product.price
            items_payload.append(
                {"product": product, "quantity": qty, "price": price, "reason": item.get("reason", "")}
            )

        order_return = OrderService.create_order_return(
            store=store,
            partner=partner,
            order=validated_data.get("order"),
            items=items_payload,
            created_by=created_by,
            reason=validated_data.get("reason", ""),
            idempotency_key=idempotency_key,
        )
        return order_return


class OrderHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderHistory
        fields = (
            "id",
            "order_type",
            "order_id",
            "product",
            "old_status",
            "new_status",
            "changed_by",
            "comment",
            "created_at",
        )
        read_only_fields = fields



