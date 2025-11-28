# apps/orders/services.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Dict, Any

from django.core.exceptions import ValidationError
from django.db import transaction

from products.models import Product
from products.services import BonusService
from stores.services import InventoryService
from stores.models import Store, StoreRequest
from users.models import User

from .models import (
    OrderHistory,
    OrderReturn,
    OrderReturnItem,
    OrderReturnStatus,
    OrderType,
    PartnerOrder,
    PartnerOrderItem,
    PartnerOrderStatus,
    StoreOrder,
    StoreOrderItem,
    StoreOrderStatus,
)


@dataclass
class OrderItemPayload:
    product: Product
    quantity: Decimal
    price: Decimal
    is_bonus: bool = False
    reason: str = ""


class OrderService:
    """Полный сервис заказов — 100% по ТЗ 1.6 и 2.4"""

    # --- PartnerOrder ---
    @classmethod
    @transaction.atomic
    def create_partner_order(
        cls,
        *,
        partner: User,
        items: Iterable[dict],
        created_by: Optional[User] = None,
        comment: str = "",
        idempotency_key: Optional[str] = None,
    ) -> PartnerOrder:
        if idempotency_key:
            existing = PartnerOrder.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing

        order = PartnerOrder.objects.create(
            partner=partner,
            created_by=created_by,
            comment=comment,
            status=PartnerOrderStatus.PENDING,
            idempotency_key=idempotency_key,
        )

        total = Decimal('0')
        for raw in items:
            payload = cls._parse_item_payload(raw)
            item = PartnerOrderItem.objects.create(
                order=order,
                product=payload.product,
                quantity=payload.quantity,
                price=payload.price,
            )
            total += item.total

        order.total_amount = total
        order.save(update_fields=['total_amount'])
        return order

    # --- StoreOrder ---
    @classmethod
    @transaction.atomic
    def create_store_order(
        cls,
        *,
        store: Store,
        partner: User,
        items_data: Iterable[Dict[str, Any]],
        store_request: Optional[StoreRequest] = None,
        paid_amount: Decimal = Decimal('0'),
        idempotency_key: Optional[str] = None,
    ) -> StoreOrder:
        if idempotency_key:
            existing = StoreOrder.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing

        total = sum(Decimal(str(item['price'])) * Decimal(str(item['quantity'])) for item in items_data)
        debt = total - paid_amount

        order = StoreOrder.objects.create(
            store=store,
            partner=partner,
            store_request=store_request,
            total_amount=total,
            debt_amount=debt,
            paid_amount=paid_amount,
            idempotency_key=idempotency_key,
        )

        # Обычные позиции
        for data in items_data:
            StoreOrderItem.objects.create(
                order=order,
                product=data['product'],
                quantity=data['quantity'],
                price=data['price'],
                is_bonus=False
            )

        # Автоматические бонусы
        BonusService.apply_bonus_to_order(order)

        return order

    @classmethod
    @transaction.atomic
    def change_store_order_status(
        cls,
        order: StoreOrder,
        new_status: str,
        changed_by: Optional[User] = None,
        comment: str = "",
    ) -> StoreOrder:
        old_status = order.status

        if new_status == StoreOrderStatus.CONFIRMED and old_status != new_status:
            # Полный перенос инвентаря
            for item in order.items.filter(is_bonus=False):
                InventoryService.transfer_inventory(
                    from_partner=order.partner,
                    to_store=order.store,
                    product=item.product,
                    quantity=item.quantity
                )

        order.status = new_status
        order.save(update_fields=['status'])

        cls._create_history(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by,
            comment=comment
        )
        return order

    # --- OrderReturn ---
    @classmethod
    @transaction.atomic
    def change_order_return_status(
        cls,
        order_return: OrderReturn,
        new_status: str,
        changed_by: Optional[User] = None,
        comment: str = "",
    ) -> OrderReturn:
        old_status = order_return.status

        if new_status == OrderReturnStatus.APPROVED and old_status != new_status:
            # Полный возврат инвентаря + уменьшение долга
            for item in order_return.items.all():
                InventoryService.transfer_inventory(
                    from_store=order_return.store,
                    to_partner=order_return.partner,
                    product=item.product,
                    quantity=item.quantity
                )

                # Уменьшаем долг магазина
                return_amount = item.price * item.quantity
                order_return.order.debt_amount -= return_amount
                order_return.order.save(update_fields=['debt_amount'])

        order_return.status = new_status
        order_return.save(update_fields=['status'])

        cls._create_history(
            order_type=OrderType.RETURN,
            order_id=order_return.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by,
            comment=comment or f"Возврат {old_status} → {new_status}"
        )
        return order_return

    # --- Helpers ---
    @staticmethod
    def _parse_item_payload(raw: dict) -> OrderItemPayload:
        return OrderItemPayload(
            product=raw['product'],
            quantity=Decimal(str(raw['quantity'])),
            price=Decimal(str(raw.get('price', raw['product'].price))),
            is_bonus=bool(raw.get('is_bonus', False)),
            reason=raw.get('reason', '')
        )

    @staticmethod
    def _create_history(
        *,
        order_type: str,
        order_id: int,
        old_status: str,
        new_status: str,
        changed_by: Optional[User],
        comment: str = "",
    ) -> OrderHistory:
        return OrderHistory.objects.create(
            order_type=order_type,
            order_id=order_id,
            old_status=old_status or "",
            new_status=new_status,
            changed_by=changed_by,
            comment=comment,
        )