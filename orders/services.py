# apps/orders/services.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.3
"""
Сервисы для orders согласно ТЗ v2.0.

ИСПРАВЛЕНИЯ v2.3:
1. admin_approve_order - НЕ добавляет товары в StoreInventory (только меняет статус)
2. Товары в StoreInventory добавляются ТОЛЬКО при подтверждении партнёром
3. Корзина магазина = заказы IN_TRANSIT (StoreOrderItem)
4. Инвентарь = товары из ACCEPTED заказов

WORKFLOW:
1. Магазин создаёт заказ → PENDING
2. Админ одобряет → IN_TRANSIT (товары в корзине = StoreOrderItem)
3. Партнёр подтверждает корзину → ACCEPTED (товары → StoreInventory)
4. Брак выбирается из StoreInventory
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from products.models import Product
from stores.models import Store, StoreInventory
from stores.services import StoreInventoryService

from .models import (
    StoreOrder,
    StoreOrderItem,
    StoreOrderStatus,
    OrderHistory,
    OrderType,
    PartnerRequest,
    PartnerRequestType,
    PartnerRequestStatus,
    ReturnedItem,
)


@dataclass
class OrderItemData:
    """Данные для создания позиции заказа."""
    product_id: int
    quantity: Decimal
    price: Optional[Decimal] = None
    is_bonus: bool = False


class OrderWorkflowService:
    """
    Сервис workflow заказов (ТЗ v2.0).

    WORKFLOW:
    1. Магазин создаёт заказ → PENDING
    2. Админ одобряет → IN_TRANSIT (товары остаются в StoreOrderItem - "корзина")
    3. Партнёр подтверждает → ACCEPTED (товары → StoreInventory)
    """

    # =========================================================================
    # СОЗДАНИЕ ЗАКАЗА (МАГАЗИН)
    # =========================================================================

    @classmethod
    @transaction.atomic
    def create_store_order(
            cls,
            *,
            store: Store,
            items_data: List[OrderItemData],
            created_by,
            idempotency_key: Optional[str] = None
    ) -> StoreOrder:
        """
        Магазин создаёт заказ (ТЗ v2.0).

        Args:
            store: Магазин
            items_data: Список товаров
            created_by: Пользователь
            idempotency_key: Ключ идемпотентности

        Returns:
            StoreOrder
        """
        # Проверка идемпотентности
        if idempotency_key:
            existing = StoreOrder.objects.filter(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                return existing

        # Проверка магазина
        if not store.can_interact:
            raise ValidationError(
                f'Магазин "{store.name}" не может создавать заказы. '
                f'Статус: {store.get_approval_status_display()}'
            )

        # Валидация и создание позиций
        total_amount = Decimal('0')
        items_to_create = []

        for item_data in items_data:
            try:
                product = Product.objects.get(
                    pk=item_data.product_id,
                    is_active=True
                )
            except Product.DoesNotExist:
                raise ValidationError(
                    f'Товар с ID {item_data.product_id} не найден или неактивен'
                )

            quantity = Decimal(str(item_data.quantity))

            # Валидация весовых товаров
            if product.is_weight_based:
                cls._validate_weight_quantity(product, quantity)

            # Проверка наличия на складе
            if product.stock_quantity < quantity:
                raise ValidationError(
                    f'Недостаточно товара "{product.name}" на складе. '
                    f'Доступно: {product.stock_quantity}, запрошено: {quantity}'
                )

            # Цена
            price = item_data.price or product.final_price
            item_total = quantity * price

            items_to_create.append({
                'product': product,
                'quantity': quantity,
                'price': price,
                'total': item_total,
                'is_bonus': item_data.is_bonus,
            })

            total_amount += item_total

        # Создание заказа
        order = StoreOrder.objects.create(
            store=store,
            status=StoreOrderStatus.PENDING,
            total_amount=total_amount,
            idempotency_key=idempotency_key,
            created_by=created_by,
        )

        # Создание позиций
        for item in items_to_create:
            StoreOrderItem.objects.create(
                order=order,
                product=item['product'],
                quantity=item['quantity'],
                price=item['price'],
                total=item['total'],
                is_bonus=item['is_bonus'],
            )

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status='',
            new_status=StoreOrderStatus.PENDING,
            changed_by=created_by,
            comment=f'Заказ создан магазином "{store.name}"'
        )

        return order

    @classmethod
    def _validate_weight_quantity(cls, product: Product, quantity: Decimal) -> None:
        """Валидация количества для весовых товаров."""
        # Минимум 1 кг (или 0.1 кг если остаток < 1 кг)
        min_qty = Decimal('1') if product.stock_quantity >= 1 else Decimal('0.1')
        if quantity < min_qty:
            raise ValidationError(
                f'Минимальное количество для "{product.name}" - {min_qty} кг'
            )

        # Шаг 0.1 кг
        if (quantity * 10) % 1 != 0:
            raise ValidationError(
                f'Количество для "{product.name}" должно быть кратно 0.1 кг'
            )

    # =========================================================================
    # ОДОБРЕНИЕ АДМИНОМ (PENDING → IN_TRANSIT)
    # =========================================================================

    @classmethod
    @transaction.atomic
    def admin_approve_order(
            cls,
            *,
            order: StoreOrder,
            admin_user,
            assign_to_partner=None
    ) -> StoreOrder:
        """
        Админ одобряет заказ (ТЗ v2.0).

        ВАЖНО: Товары НЕ добавляются в StoreInventory!
        Они остаются в StoreOrderItem и образуют "корзину" для партнёра.

        Args:
            order: Заказ
            admin_user: Админ
            assign_to_partner: Партнёр (опционально)

        Returns:
            StoreOrder
        """
        if order.status != StoreOrderStatus.PENDING:
            raise ValidationError(
                f'Невозможно одобрить заказ в статусе "{order.get_status_display()}"'
            )

        # Проверка наличия товаров на складе и уменьшение остатков
        order_items = order.items.select_related('product').all()

        for item in order_items:
            product = item.product

            if product.stock_quantity < item.quantity:
                raise ValidationError(
                    f'Недостаточно товара "{product.name}" на складе. '
                    f'Доступно: {product.stock_quantity}, требуется: {item.quantity}'
                )

        # Уменьшаем остатки на складе
        for item in order_items:
            product = item.product
            product.stock_quantity -= item.quantity

            if product.stock_quantity <= Decimal('0'):
                product.stock_quantity = Decimal('0')
                product.is_available = False

            product.save(update_fields=['stock_quantity', 'is_available'])

        # ❌ УБРАНО: Добавление в StoreInventory
        # Товары остаются в StoreOrderItem и образуют "корзину"

        # Изменение статуса
        old_status = order.status
        order.status = StoreOrderStatus.IN_TRANSIT
        order.reviewed_by = admin_user
        order.reviewed_at = timezone.now()

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
            comment=(
                f'Заказ одобрен админом. '
                f'Товары в корзине магазина "{order.store.name}". '
                f'Ожидает подтверждения партнёром.'
            )
        )

        return order

    # =========================================================================
    # ПРИНЯТИЕ ПАРТНЁРОМ (v3.0) - PENDING → IN_TRANSIT
    # =========================================================================

    @classmethod
    @transaction.atomic
    def partner_accept_preorder(
            cls,
            *,
            order: StoreOrder,
            partner_user,
    ) -> StoreOrder:
        """
        Партнёр принимает предзаказ (ТЗ v3.0).

        ИЗМЕНЕНИЕ v3.0:
        - Вместо админа заказ принимает партнёр
        - PENDING → IN_TRANSIT
        - Товары уменьшаются на складе
        - Заказ появляется в "корзине" магазина

        Args:
            order: Заказ со статусом PENDING
            partner_user: Партнёр

        Returns:
            StoreOrder

        Raises:
            ValidationError: При ошибках
        """
        import logging
        logger = logging.getLogger(__name__)

        # Валидация
        if partner_user.role != 'partner':
            raise ValidationError('Только партнёры могут принимать предзаказы')

        if order.status != StoreOrderStatus.PENDING:
            raise ValidationError(
                f'Невозможно принять заказ в статусе "{order.get_status_display()}"'
            )

        if order.order_type != 'preorder':
            raise ValidationError(
                f'Только предзаказы можно принимать. Текущий тип: {order.order_type}'
            )

        # Проверка наличия товаров на складе и уменьшение остатков
        order_items = order.items.select_related('product').all()

        for item in order_items:
            product = item.product

            if product.stock_quantity < item.quantity:
                raise ValidationError(
                    f'Недостаточно товара "{product.name}" на складе. '
                    f'Доступно: {product.stock_quantity}, требуется: {item.quantity}'
                )

        # Уменьшаем остатки на складе
        for item in order_items:
            product = item.product
            product.stock_quantity -= item.quantity

            if product.stock_quantity <= Decimal('0'):
                product.stock_quantity = Decimal('0')
                product.is_available = False

            product.save(update_fields=['stock_quantity', 'is_available'])

        # Изменение статуса
        old_status = order.status
        order.status = StoreOrderStatus.IN_TRANSIT
        order.partner = partner_user
        order.reviewed_by = partner_user
        order.reviewed_at = timezone.now()

        order.save(update_fields=['status', 'partner', 'reviewed_by', 'reviewed_at'])

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=StoreOrderStatus.IN_TRANSIT,
            changed_by=partner_user,
            comment=(
                f'Предзаказ принят партнёром {partner_user.get_full_name()}. '
                f'Товары в корзине магазина "{order.store.name}". '
                f'Ожидает подтверждения.'
            )
        )

        logger.info(
            f"Предзаказ #{order.id} принят партнёром {partner_user.id} | "
            f"Store: {order.store.name} | Amount: {order.total_amount}"
        )

        return order

    # =========================================================================
    # ОТКЛОНЕНИЕ ПАРТНЁРОМ (v3.0) - PENDING → REJECTED
    # =========================================================================

    @classmethod
    @transaction.atomic
    def partner_reject_preorder(
            cls,
            *,
            order: StoreOrder,
            partner_user,
            reason: str = ''
    ) -> StoreOrder:
        """
        Партнёр отклоняет предзаказ (ТЗ v3.0).

        Args:
            order: Заказ
            partner_user: Партнёр
            reason: Причина отклонения

        Returns:
            StoreOrder
        """
        import logging
        logger = logging.getLogger(__name__)

        # Валидация
        if partner_user.role != 'partner':
            raise ValidationError('Только партнёры могут отклонять предзаказы')

        if order.status != StoreOrderStatus.PENDING:
            raise ValidationError(
                f'Невозможно отклонить заказ в статусе "{order.get_status_display()}"'
            )

        old_status = order.status
        order.status = StoreOrderStatus.REJECTED
        order.partner = partner_user
        order.reviewed_by = partner_user
        order.reviewed_at = timezone.now()
        order.reject_reason = reason

        order.save(update_fields=['status', 'partner', 'reviewed_by', 'reviewed_at', 'reject_reason'])

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=StoreOrderStatus.REJECTED,
            changed_by=partner_user,
            comment=f'Предзаказ отклонён партнёром. Причина: {reason}' if reason else 'Предзаказ отклонён'
        )

        logger.info(
            f"Предзаказ #{order.id} отклонён партнёром {partner_user.id} | "
            f"Reason: {reason}"
        )

        return order

    # =========================================================================
    # ОТКЛОНЕНИЕ АДМИНОМ (PENDING → REJECTED)
    # =========================================================================

    @classmethod
    @transaction.atomic
    def admin_reject_order(
            cls,
            *,
            order: StoreOrder,
            admin_user,
            reason: str = ''
    ) -> StoreOrder:
        """
        Админ отклоняет заказ.

        Args:
            order: Заказ
            admin_user: Админ
            reason: Причина отклонения

        Returns:
            StoreOrder
        """
        if order.status != StoreOrderStatus.PENDING:
            raise ValidationError(
                f'Невозможно отклонить заказ в статусе "{order.get_status_display()}"'
            )

        old_status = order.status
        order.status = StoreOrderStatus.REJECTED
        order.reviewed_by = admin_user
        order.reviewed_at = timezone.now()
        order.reject_reason = reason

        order.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'reject_reason'])

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=StoreOrderStatus.REJECTED,
            changed_by=admin_user,
            comment=f'Заказ отклонён. Причина: {reason}' if reason else 'Заказ отклонён'
        )

        return order


class BasketService:
    """
    Сервис "Корзины магазина" для партнёра (ТЗ v2.0).

    Корзина = все товары из заказов со статусом IN_TRANSIT.

    WORKFLOW:
    1. Партнёр видит корзину (товары из IN_TRANSIT заказов)
    2. Может удалить товары, изменить количество
    3. Вводит предоплату
    4. Подтверждает → заказы становятся ACCEPTED
    5. Товары переносятся в StoreInventory
    6. Корзина очищается (т.к. нет больше IN_TRANSIT заказов)
    """

    @classmethod
    def get_basket(cls, store: Store) -> dict:
        """
        Получить корзину магазина (все IN_TRANSIT заказы).

        Args:
            store: Магазин

        Returns:
            dict с товарами корзины
        """
        from django.db.models import Sum

        # Получаем все IN_TRANSIT заказы
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).prefetch_related('items__product__images').order_by('created_at')

        if not orders.exists():
            return {
                'store_id': store.id,
                'store_name': store.name,
                'is_empty': True,
                'orders_count': 0,
                'items': [],
                'totals': {
                    'piece_count': 0,
                    'weight_total': '0',
                    'total_amount': '0',
                }
            }

        # Агрегируем товары из всех заказов
        items_map = {}  # product_id -> aggregated data

        for order in orders:
            for item in order.items.all():
                product = item.product
                product_id = product.id

                if product_id not in items_map:
                    # Получаем изображение
                    main_image = None
                    if hasattr(product, 'images'):
                        first_image = product.images.first()
                        if first_image and first_image.image:
                            main_image = first_image.image.url

                    items_map[product_id] = {
                        'product_id': product_id,
                        'product_name': product.name,
                        'product_image': main_image,
                        'is_weight_based': product.is_weight_based,
                        'is_bonus_product': product.is_bonus,
                        'unit': product.unit,
                        'price': item.price,  # Цена из заказа (зафиксированная)
                        'quantity': Decimal('0'),
                        'total': Decimal('0'),
                        'order_ids': [],  # Из каких заказов
                    }

                items_map[product_id]['quantity'] += item.quantity
                items_map[product_id]['total'] += item.total
                if order.id not in items_map[product_id]['order_ids']:
                    items_map[product_id]['order_ids'].append(order.id)

        # Форматируем результат
        items = []
        piece_count = 0
        weight_total = Decimal('0')
        total_amount = Decimal('0')

        for product_id, data in items_map.items():
            # Форматируем количество
            if data['is_weight_based']:
                qty = data['quantity']
                if qty == int(qty):
                    quantity_display = f"{int(qty)} кг"
                else:
                    quantity_display = f"{qty} кг"
                weight_total += data['quantity']
            else:
                quantity_display = f"{int(data['quantity'])} шт"
                piece_count += int(data['quantity'])

            total_amount += data['total']

            items.append({
                'product_id': data['product_id'],
                'product_name': data['product_name'],
                'product_image': data['product_image'],
                'is_weight_based': data['is_weight_based'],
                'is_bonus_product': data['is_bonus_product'],
                'unit': data['unit'],
                'quantity': str(data['quantity']),
                'quantity_display': quantity_display,
                'price': str(data['price']),
                'total': str(data['total']),
                'order_ids': data['order_ids'],
            })

        return {
            'store_id': store.id,
            'store_name': store.name,
            'is_empty': False,
            'orders_count': orders.count(),
            'order_ids': list(orders.values_list('id', flat=True)),
            'items': items,
            'totals': {
                'piece_count': piece_count,
                'weight_total': str(weight_total) if weight_total == int(weight_total) else str(weight_total),
                'total_amount': str(total_amount),
            }
        }

    @classmethod
    @transaction.atomic
    def confirm_basket(
            cls,
            *,
            store: Store,
            partner_user,
            prepayment_amount: Decimal = Decimal('0'),
            items_to_remove: List[int] = None,
            items_to_modify: List[dict] = None,
    ) -> dict:
        """
        Партнёр подтверждает корзину магазина.

        Args:
            store: Магазин
            partner_user: Партнёр
            prepayment_amount: Предоплата
            items_to_remove: ID товаров для удаления
            items_to_modify: Изменение количества [{"product_id": 1, "new_quantity": 10}]

        Returns:
            dict с результатом

        WORKFLOW:
        1. Удаляем/изменяем товары в StoreOrderItem
        2. Пересчитываем суммы заказов
        3. Меняем статус заказов: IN_TRANSIT → ACCEPTED
        4. Добавляем товары в StoreInventory
        5. Создаём долг
        """
        import logging
        logger = logging.getLogger(__name__)

        items_to_remove = items_to_remove or []
        items_to_modify = items_to_modify or []

        # Проверка партнёра
        if partner_user.role != 'partner':
            raise ValidationError('Только партнёры могут подтверждать корзину')

        # Получаем IN_TRANSIT заказы
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).select_for_update().prefetch_related('items__product')

        if not orders.exists():
            raise ValidationError('Нет заказов для подтверждения')

        # =====================================================================
        # 1. УДАЛЕНИЕ ТОВАРОВ
        # =====================================================================
        removed_info = []

        for product_id in items_to_remove:
            # Удаляем из ВСЕХ заказов
            deleted_items = StoreOrderItem.objects.filter(
                order__in=orders,
                product_id=product_id
            )

            for item in deleted_items:
                removed_info.append({
                    'product_id': product_id,
                    'product_name': item.product.name,
                    'quantity': float(item.quantity),
                    'order_id': item.order_id,
                })

                # Возвращаем товар на склад
                item.product.stock_quantity += item.quantity
                item.product.save(update_fields=['stock_quantity'])

            deleted_items.delete()

            logger.info(f"Удалён товар {product_id} из корзины магазина {store.id}")

        # =====================================================================
        # 2. ИЗМЕНЕНИЕ КОЛИЧЕСТВА
        # =====================================================================
        modified_info = []

        for mod in items_to_modify:
            product_id = mod.get('product_id')
            new_quantity = mod.get('new_quantity')

            if not product_id or new_quantity is None:
                continue

            new_quantity = Decimal(str(new_quantity))

            # Находим все позиции с этим товаром
            items = StoreOrderItem.objects.filter(
                order__in=orders,
                product_id=product_id
            ).select_related('product')

            if not items.exists():
                continue

            # Считаем текущее общее количество
            current_total = sum(item.quantity for item in items)

            if new_quantity >= current_total:
                # Нельзя увеличивать
                continue

            if new_quantity <= 0:
                # Удаляем все позиции
                for item in items:
                    item.product.stock_quantity += item.quantity
                    item.product.save(update_fields=['stock_quantity'])

                    removed_info.append({
                        'product_id': product_id,
                        'product_name': item.product.name,
                        'quantity': float(item.quantity),
                        'order_id': item.order_id,
                    })
                items.delete()
                continue

            # Уменьшаем количество пропорционально или в первом заказе
            difference = current_total - new_quantity
            first_item = items.first()
            product = first_item.product

            if first_item.quantity >= difference:
                # Достаточно уменьшить первую позицию
                old_qty = first_item.quantity
                first_item.quantity -= difference
                first_item.total = first_item.quantity * first_item.price
                first_item.save(update_fields=['quantity', 'total'])

                # Возвращаем на склад
                product.stock_quantity += difference
                product.save(update_fields=['stock_quantity'])

                modified_info.append({
                    'product_id': product_id,
                    'product_name': product.name,
                    'old_quantity': float(old_qty),
                    'new_quantity': float(first_item.quantity),
                    'order_id': first_item.order_id,
                })
            else:
                # Нужно удалить несколько позиций
                remaining_to_remove = difference
                for item in items:
                    if remaining_to_remove <= 0:
                        break

                    if item.quantity <= remaining_to_remove:
                        # Удаляем полностью
                        remaining_to_remove -= item.quantity
                        product.stock_quantity += item.quantity
                        product.save(update_fields=['stock_quantity'])
                        item.delete()
                    else:
                        # Уменьшаем частично
                        old_qty = item.quantity
                        item.quantity -= remaining_to_remove
                        item.total = item.quantity * item.price
                        item.save(update_fields=['quantity', 'total'])

                        product.stock_quantity += remaining_to_remove
                        product.save(update_fields=['stock_quantity'])

                        modified_info.append({
                            'product_id': product_id,
                            'product_name': product.name,
                            'old_quantity': float(old_qty),
                            'new_quantity': float(item.quantity),
                            'order_id': item.order_id,
                        })
                        remaining_to_remove = 0

            logger.info(
                f"Изменено количество товара {product_id} в корзине магазина {store.id}: "
                f"{current_total} → {new_quantity}"
            )

        # =====================================================================
        # 3. ПЕРЕСЧЁТ СУММ ЗАКАЗОВ
        # =====================================================================
        for order in orders:
            order.refresh_from_db()
            new_total = sum(
                item.total for item in order.items.all()
            )
            order.total_amount = new_total
            order.save(update_fields=['total_amount'])

        # =====================================================================
        # 4. РАСЧЁТ ОБЩЕЙ СУММЫ И ДОЛГА
        # =====================================================================
        total_amount = sum(order.total_amount for order in orders)

        # Валидация предоплаты
        if prepayment_amount < 0:
            raise ValidationError('Предоплата не может быть отрицательной')

        if prepayment_amount > total_amount:
            raise ValidationError(
                f'Предоплата ({prepayment_amount} сом) не может превышать '
                f'сумму заказов ({total_amount} сом)'
            )

        # Долг = сумма - предоплата
        total_debt = total_amount - prepayment_amount

        # Распределяем предоплату по заказам пропорционально
        remaining_prepayment = prepayment_amount

        # =====================================================================
        # 5. ПОДТВЕРЖДЕНИЕ ЗАКАЗОВ И ПЕРЕНОС В ИНВЕНТАРЬ
        # =====================================================================
        confirmed_orders = []

        for order in orders:
            # Рассчитываем предоплату для этого заказа
            if total_amount > 0:
                order_prepayment = (order.total_amount / total_amount) * prepayment_amount
            else:
                order_prepayment = Decimal('0')

            order_debt = order.total_amount - order_prepayment

            # Обновляем заказ
            old_status = order.status
            order.status = StoreOrderStatus.ACCEPTED
            order.partner = partner_user
            order.confirmed_by = partner_user
            order.confirmed_at = timezone.now()
            order.prepayment_amount = order_prepayment
            order.debt_amount = order_debt

            order.save(update_fields=[
                'status', 'partner', 'confirmed_by', 'confirmed_at',
                'prepayment_amount', 'debt_amount'
            ])

            # Переносим товары в инвентарь
            for item in order.items.all():
                StoreInventoryService.add_to_inventory(
                    store=store,
                    product=item.product,
                    quantity=item.quantity
                )

            # История
            OrderHistory.objects.create(
                order_type=OrderType.STORE,
                order_id=order.id,
                old_status=old_status,
                new_status=StoreOrderStatus.ACCEPTED,
                changed_by=partner_user,
                comment=(
                    f'Заказ подтверждён партнёром. '
                    f'Сумма: {order.total_amount} сом. '
                    f'Предоплата: {order_prepayment} сом. '
                    f'Долг: {order_debt} сом.'
                )
            )

            confirmed_orders.append({
                'order_id': order.id,
                'total_amount': float(order.total_amount),
                'prepayment': float(order_prepayment),
                'debt': float(order_debt),
            })

            logger.info(
                f"Заказ #{order.id} подтверждён | Store: {store.id} | "
                f"Amount: {order.total_amount} | Debt: {order_debt}"
            )

        # =====================================================================
        # 6. ОБНОВЛЕНИЕ ДОЛГА МАГАЗИНА
        # =====================================================================
        store = Store.objects.select_for_update().get(pk=store.pk)
        store.debt += total_debt
        store.save(update_fields=['debt'])

        logger.info(
            f"Корзина подтверждена | Store: {store.id} | "
            f"Orders: {len(confirmed_orders)} | Total Debt: {total_debt}"
        )

        return {
            'success': True,
            'message': f'Корзина подтверждена. Заказов: {len(confirmed_orders)}',
            'confirmed_orders': confirmed_orders,
            'totals': {
                'total_amount': float(total_amount),
                'prepayment': float(prepayment_amount),
                'debt_created': float(total_debt),
            },
            'store_debt': float(store.debt),
            'removed_items': removed_info,
            'modified_items': modified_info,
        }


# =============================================================================
# PARTNER REQUEST SERVICE (v3.0)
# =============================================================================

class PartnerRequestService:
    """
    Сервис для управления запросами партнёра (v3.0).
    
    ИЗМЕНЕНИЯ v3.0:
    - Поддержка нескольких товаров (items[])
    - Создание PartnerRequestItem для каждого товара
    - Поле notes вместо reason
    
    ТИПЫ ЗАПРОСОВ:
    - REQUEST: Партнёр запрашивает товары у админа
    - RETURN: Партнёр возвращает товары админу
    
    WORKFLOW REQUEST:
    1. Партнёр создаёт запрос с items[] (status=PENDING)
    2. Админ одобряет (status=APPROVED)
       - Товары добавляются в PartnerInventory
       - Количество в каталоге админа уменьшается
    3. Админ отклоняет (status=REJECTED)
    
    WORKFLOW RETURN:
    1. Партнёр создаёт возврат с items[] (status=PENDING)
       - Товары резервируются в PartnerInventory
    2. Админ одобряет (status=APPROVED)
       - Товары удаляются из PartnerInventory
       - Количество в каталоге админа увеличивается
    3. Админ отклоняет (status=REJECTED)
       - Резервирование снимается
    """
    
    @classmethod
    @transaction.atomic
    def create_request(
        cls,
        *,
        partner: 'User',
        request_type: str,
        items: List[dict],
        notes: str = ''
    ) -> PartnerRequest:
        """
        Создать запрос партнёра с несколькими товарами (v3.0).
        
        Args:
            partner: Партнёр
            request_type: Тип запроса (request/return)
            items: Список товаров [{product: int, quantity: Decimal, weight: Decimal?}]
            notes: Примечания к запросу
            
        Returns:
            PartnerRequest
            
        Raises:
            ValidationError: При ошибках валидации
        """
        from stores.services import PartnerInventoryService
        from .models import PartnerRequestItem
        import logging
        logger = logging.getLogger(__name__)
        
        # Валидация
        if partner.role != 'partner':
            raise ValidationError('Только партнёры могут создавать запросы')
            
        if not items:
            raise ValidationError('Список товаров не может быть пустым')
            
        if request_type not in [PartnerRequestType.REQUEST, PartnerRequestType.RETURN]:
            raise ValidationError(f'Неверный тип запроса: {request_type}')
        
        # Создаём запрос (без product/quantity - они теперь в items)
        request = PartnerRequest.objects.create(
            partner=partner,
            request_type=request_type,
            status=PartnerRequestStatus.PENDING,
            notes=notes
        )
        
        # Создаём позиции запроса
        for item_data in items:
            product_id = item_data.get('product')
            quantity = Decimal(str(item_data.get('quantity', 0)))
            weight = item_data.get('weight')
            
            try:
                product = Product.objects.get(pk=product_id)
            except Product.DoesNotExist:
                request.delete()
                raise ValidationError(f'Товар с ID {product_id} не найден')
            
            # Для весовых товаров: используем weight как основную величину
            # Мобильное приложение передаёт 0.001 как заглушку в quantity для весовых товаров
            if product.is_weight_based:
                if not weight:
                    request.delete()
                    raise ValidationError(f'Для весового товара "{product.name}" необходимо указать вес')
                weight = Decimal(str(weight))
                if weight <= Decimal('0'):
                    request.delete()
                    raise ValidationError(f'Вес должен быть больше 0 для товара "{product.name}"')
                if weight % Decimal('0.1') != 0:
                    request.delete()
                    raise ValidationError(f'Вес товара "{product.name}" должен быть кратен 0.1 кг')
                # Для весовых товаров: quantity = weight (для совместимости с расчётами)
                effective_quantity = weight
            else:
                # Для штучных товаров: используем quantity
                if quantity <= Decimal('0'):
                    request.delete()
                    raise ValidationError(f'Количество должно быть больше 0 для товара {product_id}')
                effective_quantity = quantity
            
            # Дополнительная валидация для возврата
            if request_type == PartnerRequestType.RETURN:
                has_inventory = PartnerInventoryService.check_availability(
                    partner=partner,
                    product=product,
                    quantity=effective_quantity
                )
                if not has_inventory:
                    request.delete()
                    raise ValidationError(
                        f'Недостаточно товара "{product.name}" в инвентаре для возврата'
                    )
                
                # Резервируем товары
                PartnerInventoryService.reserve_quantity(
                    partner=partner,
                    product=product,
                    quantity=effective_quantity
                )
            
            # Создаём позицию
            # Для весовых: quantity = weight (для правильного расчёта суммы)
            PartnerRequestItem.objects.create(
                request=request,
                product=product,
                quantity=effective_quantity,
                weight=weight if product.is_weight_based else None,
                price_at_request=product.final_price
            )
        
        logger.info(
            f"Создан запрос партнёра #{request.id} | "
            f"Partner: {partner.id} | Type: {request_type} | "
            f"Items: {len(items)}"
        )
        
        return request
    
    @classmethod
    @transaction.atomic
    def approve_request(
        cls,
        *,
        request: PartnerRequest,
        approved_by: 'User'
    ) -> PartnerRequest:
        """
        Одобрить запрос партнёра (только админ).
        
        v3.0: Поддержка нескольких товаров через items.
        
        Args:
            request: Запрос
            approved_by: Кто одобрил (админ)
            
        Returns:
            PartnerRequest
            
        Raises:
            ValidationError: При ошибках
        """
        from stores.services import PartnerInventoryService
        import logging
        logger = logging.getLogger(__name__)
        
        # Валидация
        if approved_by.role != 'admin':
            raise ValidationError('Только админ может одобрять запросы')
            
        if request.status != PartnerRequestStatus.PENDING:
            raise ValidationError(
                f'Запрос уже обработан (статус: {request.get_status_display()})'
            )
        
        partner = request.partner
        
        # v3.0: Работаем с items (несколько товаров)
        items = request.items.select_related('product').all()
        
        if not items.exists():
            # Обратная совместимость: старая логика (один товар)
            if request.product and request.quantity:
                # Создаём временный объект для итерации
                class LegacyItem:
                    def __init__(self, product, quantity):
                        self.product = product
                        self.quantity = quantity
                items = [LegacyItem(request.product, request.quantity)]
            else:
                raise ValidationError('Запрос не содержит товаров')
        
        if request.request_type == PartnerRequestType.REQUEST:
            # ЗАПРОС ТОВАРОВ: Админ → Партнёр
            
            # Сначала проверяем наличие ВСЕХ товаров
            for item in items:
                product = item.product
                quantity = item.quantity
                
                if product.stock_quantity < quantity:
                    raise ValidationError(
                        f'Недостаточно товара "{product.name}" на складе. '
                        f'Доступно: {product.stock_quantity}, запрошено: {quantity}'
                    )
            
            # Теперь обрабатываем товары
            for item in items:
                product = item.product
                quantity = item.quantity
                
                # Уменьшаем количество в каталоге
                product.stock_quantity -= quantity
                if product.stock_quantity <= Decimal('0'):
                    product.stock_quantity = Decimal('0')
                    product.is_available = False
                product.save(update_fields=['stock_quantity', 'is_available'])
                
                # Добавляем в инвентарь партнёра
                PartnerInventoryService.add_to_inventory(
                    partner=partner,
                    product=product,
                    quantity=quantity,
                    source_request=request
                )
                
                logger.info(
                    f"Запрос #{request.id} | "
                    f"Товар '{product.name}' x{quantity} добавлен в инвентарь партнёра {partner.id}"
                )
            
        else:  # RETURN
            # ВОЗВРАТ ТОВАРОВ: Партнёр → Админ
            for item in items:
                product = item.product
                quantity = item.quantity
                
                # Удаляем из инвентаря партнёра
                PartnerInventoryService.remove_from_inventory(
                    partner=partner,
                    product=product,
                    quantity=quantity
                )
                
                # Увеличиваем количество в каталоге
                product.stock_quantity += quantity
                product.is_available = True
                product.save(update_fields=['stock_quantity', 'is_available'])
                
                logger.info(
                    f"Возврат #{request.id} | "
                    f"Товар '{product.name}' x{quantity} возвращён на склад админа"
                )
        
        # Обновляем статус запроса
        request.status = PartnerRequestStatus.APPROVED
        request.reviewed_by = approved_by
        request.reviewed_at = timezone.now()
        request.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        
        logger.info(f"Запрос #{request.id} одобрен админом {approved_by.id}")
        
        return request
    
    @classmethod
    @transaction.atomic
    def reject_request(
        cls,
        *,
        request: PartnerRequest,
        rejected_by: 'User' = None,
        rejection_reason: str = ''
    ) -> PartnerRequest:
        """
        Отклонить запрос партнёра (только админ).
        
        v3.0: Поддержка нескольких товаров через items.
        
        Args:
            request: Запрос
            rejected_by: Кто отклонил (админ)
            rejection_reason: Причина отклонения
            
        Returns:
            PartnerRequest
            
        Raises:
            ValidationError: При ошибках
        """
        from stores.services import PartnerInventoryService
        import logging
        logger = logging.getLogger(__name__)
        
        # Валидация
        if rejected_by and rejected_by.role != 'admin':
            raise ValidationError('Только админ может отклонять запросы')
            
        if request.status != PartnerRequestStatus.PENDING:
            raise ValidationError(
                f'Запрос уже обработан (статус: {request.get_status_display()})'
            )
        
        if not rejection_reason:
            raise ValidationError('Необходимо указать причину отклонения')
        
        # Для возврата - освобождаем резервирование (v3.0: итерируем по items)
        if request.request_type == PartnerRequestType.RETURN:
            items = request.items.select_related('product').all()
            
            if items.exists():
                # v3.0: несколько товаров
                for item in items:
                    PartnerInventoryService.release_reserved(
                        partner=request.partner,
                        product=item.product,
                        quantity=item.quantity
                    )
            elif request.product and request.quantity:
                # Обратная совместимость
                PartnerInventoryService.release_reserved(
                    partner=request.partner,
                    product=request.product,
                    quantity=request.quantity
                )
        
        # Обновляем статус
        request.status = PartnerRequestStatus.REJECTED
        request.reviewed_by = rejected_by
        request.reviewed_at = timezone.now()
        request.rejection_reason = rejection_reason
        request.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'rejection_reason'
        ])
        
        logger.info(
            f"Запрос #{request.id} отклонён | "
            f"Reason: {rejection_reason}"
        )
        
        return request
    
    @classmethod
    @transaction.atomic
    def cancel_request(
        cls,
        request: PartnerRequest,
        cancelled_by: 'User' = None
    ) -> PartnerRequest:
        """
        Отменить запрос партнёром (только если PENDING).
        
        v3.0: Поддержка нескольких товаров через items.
        
        Args:
            request: Запрос
            cancelled_by: Партнёр (владелец запроса)
            
        Returns:
            PartnerRequest
            
        Raises:
            ValidationError: При ошибках
        """
        from stores.services import PartnerInventoryService
        import logging
        logger = logging.getLogger(__name__)
        
        # Валидация
        if cancelled_by and request.partner != cancelled_by:
            raise ValidationError('Только владелец запроса может его отменить')
            
        if request.status != PartnerRequestStatus.PENDING:
            raise ValidationError(
                f'Нельзя отменить обработанный запрос (статус: {request.get_status_display()})'
            )
        
        request_id = request.id
        
        # Для возврата - освобождаем резервирование (v3.0: итерируем по items)
        if request.request_type == PartnerRequestType.RETURN:
            items = request.items.select_related('product').all()
            
            if items.exists():
                # v3.0: несколько товаров
                for item in items:
                    PartnerInventoryService.release_reserved(
                        partner=request.partner,
                        product=item.product,
                        quantity=item.quantity
                    )
            elif request.product and request.quantity:
                # Обратная совместимость
                PartnerInventoryService.release_reserved(
                    partner=request.partner,
                    product=request.product,
                    quantity=request.quantity
                )
        
        # Удаляем запрос
        request.delete()
        
        logger.info(
            f"Запрос #{request_id} отменён партнёром {cancelled_by.id if cancelled_by else 'system'}"
        )
        
        return request
    
    @classmethod
    def get_partner_requests(
        cls,
        *,
        partner: 'User',
        request_type: Optional[str] = None,
        status: Optional[str] = None
    ):
        """
        Получить запросы партнёра с фильтрацией.
        
        Args:
            partner: Партнёр
            request_type: Тип запроса (опционально)
            status: Статус (опционально)
            
        Returns:
            QuerySet[PartnerRequest]
        """
        queryset = PartnerRequest.objects.filter(
            partner=partner
        ).select_related('product', 'reviewed_by').order_by('-created_at')
        
        if request_type:
            queryset = queryset.filter(request_type=request_type)
            
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset
    
    @classmethod
    def get_pending_requests_for_admin(cls):
        """
        Получить все запросы в ожидании (для админа).
        
        Returns:
            QuerySet[PartnerRequest]
        """
        return PartnerRequest.objects.filter(
            status=PartnerRequestStatus.PENDING
        ).select_related('partner', 'product').order_by('created_at')


# =============================================================================
# MANUAL ORDER SERVICE (v3.0)
# =============================================================================

class ManualOrderService:
    """
    Сервис для создания ручных заказов партнёром (v3.0).
    
    ОТЛИЧИЯ ОТ ПРЕДЗАКАЗА:
    - Партнёр сам создаёт заказ магазину
    - Товары берутся из PartnerInventory (не из каталога админа)
    - Заказ сразу в статусе ACCEPTED
    - order_type = 'manual'
    - Долг создаётся сразу
    
    WORKFLOW:
    1. Партнёр выбирает магазин
    2. Партнёр выбирает товары из своего инвентаря
    3. Указывает предоплату (опционально)
    4. Заказ создаётся с order_type='manual', status='accepted'
    5. Товары: PartnerInventory → StoreInventory
    6. Долг = total_amount - prepayment
    """
    
    @classmethod
    @transaction.atomic
    def create_manual_order(
        cls,
        *,
        partner: 'User',
        store: Store,
        items: List[OrderItemData],
        prepayment_amount: Decimal = Decimal('0'),
        notes: str = ''
    ) -> StoreOrder:
        """
        Создать ручной заказ партнёром.
        
        Args:
            partner: Партнёр
            store: Магазин
            items: Список товаров
            prepayment_amount: Сумма предоплаты
            notes: Примечания
            
        Returns:
            StoreOrder
            
        Raises:
            ValidationError: При ошибках
        """
        from stores.services import PartnerInventoryService
        import logging
        logger = logging.getLogger(__name__)
        
        # Валидация
        if partner.role != 'partner':
            raise ValidationError('Только партнёры могут создавать ручные заказы')
            
        if not store.is_active:
            raise ValidationError(f'Магазин {store.name} заблокирован')
            
        if not items:
            raise ValidationError('Заказ должен содержать хотя бы один товар')
            
        if prepayment_amount < Decimal('0'):
            raise ValidationError('Предоплата не может быть отрицательной')
        
        # Создаём заказ
        order = StoreOrder.objects.create(
            store=store,
            partner=partner,
            status=StoreOrderStatus.ACCEPTED,
            order_type='manual',  # v3.0: manual order
            confirmed_by=partner,
            confirmed_at=timezone.now(),
            prepayment_amount=prepayment_amount,
            notes=notes
        )
        
        total_amount = Decimal('0')
        
        # Обрабатываем товары
        for item_data in items:
            try:
                product = Product.objects.get(pk=item_data.product_id)
            except Product.DoesNotExist:
                raise ValidationError(f'Товар с ID {item_data.product_id} не найден')
            
            # Проверяем наличие в инвентаре партнёра
            has_inventory = PartnerInventoryService.check_availability(
                partner=partner,
                product=product,
                quantity=item_data.quantity
            )
            
            if not has_inventory:
                raise ValidationError(
                    f'Недостаточно товара {product.name} в инвентаре партнёра'
                )
            
            # Убираем из инвентаря партнёра
            PartnerInventoryService.remove_from_inventory(
                partner=partner,
                product=product,
                quantity=item_data.quantity
            )
            
            # Добавляем в инвентарь магазина
            StoreInventoryService.add_to_inventory(
                store=store,
                product=product,
                quantity=item_data.quantity
            )
            
            # Создаём позицию заказа
            price = item_data.price or product.final_price
            item_total = price * item_data.quantity
            
            StoreOrderItem.objects.create(
                order=order,
                product=product,
                quantity=item_data.quantity,
                price=price,
                total=item_total,
                is_bonus=item_data.is_bonus
            )
            
            total_amount += item_total
        
        # Обновляем заказ (округляем до 2 знаков после запятой)
        total_amount = total_amount.quantize(Decimal('0.01'))
        debt_amount = (total_amount - prepayment_amount).quantize(Decimal('0.01'))
        order.total_amount = total_amount
        order.debt_amount = debt_amount
        order.save(update_fields=['total_amount', 'debt_amount'])
        
        # Обновляем долг магазина
        store = Store.objects.select_for_update().get(pk=store.pk)
        store.debt = (store.debt + debt_amount).quantize(Decimal('0.01'))
        store.save(update_fields=['debt'])
        
        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=None,
            new_status=StoreOrderStatus.ACCEPTED,
            changed_by=partner,
            comment=(
                f'Ручной заказ создан партнёром. '
                f'Сумма: {total_amount} сом. '
                f'Предоплата: {prepayment_amount} сом. '
                f'Долг: {debt_amount} сом.'
            )
        )
        
        logger.info(
            f"Создан ручной заказ #{order.id} | "
            f"Partner: {partner.id} | Store: {store.id} | "
            f"Amount: {total_amount} | Debt: {debt_amount}"
        )
        
        return order
