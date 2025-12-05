# apps/orders/services.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Сервисы для работы с заказами согласно ТЗ v2.0.

ОСНОВНОЙ СЕРВИС:
- OrderWorkflowService: Workflow магазин → админ → партнёр

ДОПОЛНИТЕЛЬНЫЕ СЕРВИСЫ:
- PartnerOrderService: Заказы партнёра у админа
- DebtService: Управление долгами
- DefectiveProductService: Бракованные товары

ТЗ v2.0 WORKFLOW:
1. Магазин создаёт заказ → PENDING
2. Админ одобряет → IN_TRANSIT, товары → инвентарь
3. Партнёр подтверждает → ACCEPTED, создаётся долг
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Dict, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet, F, Sum
from django.utils import timezone

from stores.models import Store, StoreInventory
from stores.services import StoreInventoryService
from products.models import Product

from .models import (
    StoreOrder,
    StoreOrderItem,
    StoreOrderStatus,
    PartnerOrder,
    PartnerOrderItem,
    PartnerOrderStatus,
    DebtPayment,
    DefectiveProduct,
    OrderHistory,
    OrderType,
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class OrderItemData:
    """Данные позиции заказа."""
    product_id: int
    quantity: Decimal
    price: Optional[Decimal] = None  # Если None, берётся из Product.final_price
    is_bonus: bool = False


# =============================================================================
# ORDER WORKFLOW SERVICE (ОСНОВНОЙ)
# =============================================================================

class OrderWorkflowService:
    """
    Сервис для работы с workflow заказов магазина (ТЗ v2.0).

    WORKFLOW:
    1. create_store_order() - Магазин создаёт заказ
    2. admin_approve_order() - Админ одобряет
    3. partner_confirm_order() - Партнёр подтверждает

    ДОПОЛНИТЕЛЬНО:
    - store_cancel_items() - Магазин отменяет товары до IN_TRANSIT
    - admin_reject_order() - Админ отклоняет
    """

    # =========================================================================
    # 1. СОЗДАНИЕ ЗАКАЗА МАГАЗИНОМ
    # =========================================================================

    @classmethod
    @transaction.atomic
    def create_store_order(
            cls,
            *,
            store: Store,
            items_data: List[OrderItemData],
            created_by: Optional['User'] = None,
            idempotency_key: Optional[str] = None,
    ) -> StoreOrder:
        """
        Магазин создаёт заказ у админа (ТЗ v2.0).

        Args:
            store: Магазин
            items_data: Список товаров
            created_by: Пользователь
            idempotency_key: Защита от дублирования

        Returns:
            StoreOrder в статусе PENDING

        Raises:
            ValidationError: Если магазин заморожен или данные некорректны
        """
        # Проверка: магазин активен
        store.check_can_interact()

        # Проверка idempotency
        if idempotency_key:
            existing = StoreOrder.objects.filter(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                return existing

        # Создаём заказ
        order = StoreOrder.objects.create(
            store=store,
            partner=None,  # ← Партнёр назначается позже
            created_by=created_by,
            status=StoreOrderStatus.PENDING,
            idempotency_key=idempotency_key,
        )

        # Добавляем позиции
        total_amount = Decimal('0')

        for item_data in items_data:
            product = Product.objects.get(pk=item_data.product_id)

            # Валидация товара
            if not product.is_active or not product.is_available:
                raise ValidationError(
                    f"Товар '{product.name}' недоступен для заказа"
                )

            # Валидация количества (весовые товары)
            if hasattr(product, 'validate_order_quantity'):
                product.validate_order_quantity(item_data.quantity)

            # Цена
            price = item_data.price or product.final_price

            # Создаём позицию
            item = StoreOrderItem.objects.create(
                order=order,
                product=product,
                quantity=item_data.quantity,
                price=price,
                is_bonus=item_data.is_bonus
            )

            total_amount += item.total

        # Обновляем сумму
        order.total_amount = total_amount
        order.save(update_fields=['total_amount'])

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status='',
            new_status=StoreOrderStatus.PENDING,
            changed_by=created_by,
            comment=f'Заказ создан магазином {store.name}'
        )

        return order

    # =========================================================================
    # 2. АДМИН ОДОБРЯЕТ ЗАКАЗ
    # =========================================================================

    @classmethod
    @transaction.atomic
    def admin_approve_order(
            cls,
            *,
            order: StoreOrder,
            admin_user: 'User',
            assign_to_partner: Optional['User'] = None,
    ) -> StoreOrder:
        """
        Админ одобряет заказ (ТЗ v2.0).

        Действия:
        1. Статус → IN_TRANSIT
        2. Товары → инвентарь магазина
        3. Опционально назначить партнёра

        Args:
            order: Заказ
            admin_user: Администратор
            assign_to_partner: Партнёр (опционально)

        Returns:
            StoreOrder в статусе IN_TRANSIT
        """
        # Проверки
        if admin_user.role != 'admin':
            raise ValidationError("Только администратор может одобрять заказы")

        if order.status != StoreOrderStatus.PENDING:
            raise ValidationError(
                f"Можно одобрить только заказы в статусе 'В ожидании'. "
                f"Текущий: {order.get_status_display()}"
            )

        # Добавляем товары в инвентарь магазина
        for item in order.items.all():
            StoreInventoryService.add_to_inventory(
                store=order.store,
                product=item.product,
                quantity=item.quantity
            )

        # Меняем статус
        old_status = order.status
        order.status = StoreOrderStatus.IN_TRANSIT
        order.reviewed_by = admin_user
        order.reviewed_at = timezone.now()

        # Назначаем партнёра (опционально)
        if assign_to_partner:
            if assign_to_partner.role != 'partner':
                raise ValidationError("Можно назначить только партнёра")
            order.partner = assign_to_partner

        order.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'partner'])

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=StoreOrderStatus.IN_TRANSIT,
            changed_by=admin_user,
            comment='Заказ одобрен админом, товары добавлены в инвентарь'
        )

        return order

    # =========================================================================
    # 3. АДМИН ОТКЛОНЯЕТ ЗАКАЗ
    # =========================================================================

    @classmethod
    @transaction.atomic
    def admin_reject_order(
            cls,
            *,
            order: StoreOrder,
            admin_user: 'User',
            reason: str = '',
    ) -> StoreOrder:
        """Админ отклоняет заказ."""
        if admin_user.role != 'admin':
            raise ValidationError("Только администратор может отклонять заказы")

        if order.status != StoreOrderStatus.PENDING:
            raise ValidationError("Можно отклонить только заказы в статусе 'В ожидании'")

        old_status = order.status
        order.status = StoreOrderStatus.REJECTED
        order.reviewed_by = admin_user
        order.reviewed_at = timezone.now()
        order.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])

        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=StoreOrderStatus.REJECTED,
            changed_by=admin_user,
            comment=f'Заказ отклонён. Причина: {reason or "Не указана"}'
        )

        return order

    # =========================================================================
    # 4. ПАРТНЁР ПОДТВЕРЖДАЕТ ЗАКАЗ
    # =========================================================================

    @classmethod
    @transaction.atomic
    def partner_confirm_order(
            cls,
            *,
            order: StoreOrder,
            partner_user: 'User',
            prepayment_amount: Decimal = Decimal('0'),
            items_to_remove_from_inventory: Optional[List[int]] = None,
    ) -> StoreOrder:
        """
        Партнёр подтверждает заказ (ТЗ v2.0).

        Действия:
        1. Партнёр может удалить товары из инвентаря
        2. Указывает предоплату
        3. Создаётся долг: total - prepayment
        4. Статус → ACCEPTED

        Args:
            order: Заказ
            partner_user: Партнёр
            prepayment_amount: Предоплата
            items_to_remove_from_inventory: ID продуктов для удаления

        Returns:
            StoreOrder в статусе ACCEPTED
        """
        # Проверки
        if partner_user.role != 'partner':
            raise ValidationError("Только партнёр может подтверждать заказы")

        if order.status != StoreOrderStatus.IN_TRANSIT:
            raise ValidationError("Можно подтвердить только заказы в статусе 'В пути'")

        if prepayment_amount < Decimal('0'):
            raise ValidationError("Предоплата не может быть отрицательной")

        if prepayment_amount > order.total_amount:
            raise ValidationError(
                f"Предоплата ({prepayment_amount}) не может превышать "
                f"сумму заказа ({order.total_amount})"
            )

        # Удаляем товары из инвентаря (если партнёр отменил)
        if items_to_remove_from_inventory:
            for product_id in items_to_remove_from_inventory:
                try:
                    order_item = order.items.filter(product_id=product_id).first()
                    if order_item:
                        # Удаляем из инвентаря
                        StoreInventoryService.remove_from_inventory(
                            store=order.store,
                            product=order_item.product,
                            quantity=order_item.quantity
                        )

                        # Удаляем позицию из заказа
                        order_item.delete()

                except Exception as e:
                    # Логируем, но не останавливаем процесс
                    pass

            # Пересчитываем сумму
            order.recalc_total()

        # Применяем предоплату
        order.prepayment_amount = prepayment_amount
        order.debt_amount = order.total_amount - prepayment_amount

        # Обновляем долг магазина
        order.store.debt = F('debt') + order.debt_amount
        order.store.save(update_fields=['debt'])

        # Меняем статус
        old_status = order.status
        order.status = StoreOrderStatus.ACCEPTED
        order.partner = partner_user
        order.confirmed_by = partner_user
        order.confirmed_at = timezone.now()
        order.save()

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=StoreOrderStatus.ACCEPTED,
            changed_by=partner_user,
            comment=(
                f'Заказ подтверждён партнёром. '
                f'Предоплата: {prepayment_amount} сом, '
                f'Долг: {order.debt_amount} сом'
            )
        )

        return order

    # =========================================================================
    # 5. МАГАЗИН ОТМЕНЯЕТ ТОВАРЫ ДО IN_TRANSIT
    # =========================================================================

    @classmethod
    @transaction.atomic
    def store_cancel_items(
            cls,
            *,
            order: StoreOrder,
            item_ids_to_cancel: List[int],
            cancelled_by: 'User',
    ) -> StoreOrder:
        """
        Магазин отменяет товары до IN_TRANSIT (ТЗ v2.0).

        Args:
            order: Заказ
            item_ids_to_cancel: ID позиций
            cancelled_by: Пользователь

        Returns:
            Обновлённый StoreOrder
        """
        if order.status not in [StoreOrderStatus.PENDING]:
            raise ValidationError(
                "Отменить товары можно только в статусе 'В ожидании'"
            )

        # Удаляем позиции
        cancelled_items = order.items.filter(id__in=item_ids_to_cancel)
        cancelled_count = cancelled_items.count()
        cancelled_items.delete()

        # Пересчитываем сумму
        order.recalc_total()

        # Если все товары отменены
        if not order.items.exists():
            order.status = StoreOrderStatus.REJECTED
            order.save(update_fields=['status'])

            OrderHistory.objects.create(
                order_type=OrderType.STORE,
                order_id=order.id,
                old_status=StoreOrderStatus.PENDING,
                new_status=StoreOrderStatus.REJECTED,
                changed_by=cancelled_by,
                comment='Заказ отменён - все товары удалены'
            )
        else:
            OrderHistory.objects.create(
                order_type=OrderType.STORE,
                order_id=order.id,
                old_status=order.status,
                new_status=order.status,
                changed_by=cancelled_by,
                comment=f'Магазин отменил {cancelled_count} позиций'
            )

        return order

    # =========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # =========================================================================

    @classmethod
    def get_orders_for_partner(
            cls,
            partner: 'User',
            status: Optional[StoreOrderStatus] = None,
    ) -> QuerySet[StoreOrder]:
        """
        Получить заказы для партнёра.

        ТЗ: "Партнёр видит только заказы в статусе IN_TRANSIT"
        """
        if partner.role != 'partner':
            raise ValidationError("Только партнёр может просматривать заказы")

        queryset = StoreOrder.objects.filter(
            status=StoreOrderStatus.IN_TRANSIT
        )

        if status:
            queryset = queryset.filter(status=status)

        return queryset.select_related('store', 'reviewed_by')

    @classmethod
    def get_store_orders(
            cls,
            store: Store,
            status: Optional[StoreOrderStatus] = None,
    ) -> QuerySet[StoreOrder]:
        """Получить заказы магазина."""
        queryset = StoreOrder.objects.filter(store=store)

        if status:
            queryset = queryset.filter(status=status)

        return queryset.select_related('partner', 'reviewed_by', 'confirmed_by')


# =============================================================================
# DEBT SERVICE
# =============================================================================

class DebtService:
    """Сервис для управления долгами."""

    @classmethod
    @transaction.atomic
    def pay_order_debt(
            cls,
            *,
            order: StoreOrder,
            amount: Decimal,
            paid_by: Optional['User'] = None,
            received_by: Optional['User'] = None,
            comment: str = '',
    ) -> DebtPayment:
        """Погашение долга по заказу."""
        return order.pay_debt(
            amount=amount,
            paid_by=paid_by,
            received_by=received_by,
            comment=comment
        )

    @classmethod
    def get_store_total_debt(cls, store: Store) -> Decimal:
        """Общий долг магазина."""
        return store.debt

    @classmethod
    def get_store_debt_by_orders(cls, store: Store) -> List[Dict[str, Any]]:
        """Долги магазина по заказам."""
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED
        ).annotate(
            outstanding=F('debt_amount') - F('paid_amount')
        ).filter(outstanding__gt=Decimal('0'))

        return [
            {
                'order_id': order.id,
                'total_amount': order.total_amount,
                'debt_amount': order.debt_amount,
                'paid_amount': order.paid_amount,
                'outstanding_debt': order.outstanding_debt,
                'created_at': order.created_at
            }
            for order in orders
        ]


# =============================================================================
# DEFECTIVE PRODUCT SERVICE
# =============================================================================

class DefectiveProductService:
    """Сервис для работы с бракованными товарами."""

    @classmethod
    @transaction.atomic
    def report_defect(
            cls,
            *,
            order: StoreOrder,
            product: Product,
            quantity: Decimal,
            price: Decimal,
            reason: str,
            reported_by: 'User',
    ) -> DefectiveProduct:
        """
        Магазин заявляет о браке.

        Args:
            order: Заказ
            product: Товар
            quantity: Количество брака
            price: Цена
            reason: Причина
            reported_by: Кто сообщил

        Returns:
            DefectiveProduct
        """
        defect = DefectiveProduct.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            price=price,
            reason=reason,
            reported_by=reported_by,
            status=DefectiveProduct.DefectStatus.PENDING
        )

        return defect

    @classmethod
    @transaction.atomic
    def approve_defect(
            cls,
            *,
            defect: DefectiveProduct,
            approved_by: 'User',
    ) -> DefectiveProduct:
        """
        Партнёр подтверждает брак → уменьшается долг.

        Args:
            defect: Бракованный товар
            approved_by: Партнёр

        Returns:
            DefectiveProduct
        """
        if approved_by.role != 'partner':
            raise ValidationError("Только партнёр может подтверждать брак")

        defect.approve(approved_by=approved_by)

        return defect

    @classmethod
    def get_pending_defects(cls, order: StoreOrder) -> QuerySet[DefectiveProduct]:
        """Ожидающие проверки дефекты."""
        return DefectiveProduct.objects.filter(
            order=order,
            status=DefectiveProduct.DefectStatus.PENDING
        )