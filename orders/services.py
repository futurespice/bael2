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
    additional_price_id: Optional[int] = None


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
        else:
            # Fallback: проверка дубликата по store + время (60 сек)
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(seconds=60)
            duplicate = StoreOrder.objects.filter(
                store=store,
                created_by=created_by,
                status=StoreOrderStatus.PENDING,
                created_at__gte=cutoff
            ).first()
            if duplicate:
                return duplicate

        # Проверка магазина
        if not store.can_interact:
            raise ValidationError(
                f'Магазин "{store.name}" не может создавать заказы. '
                f'Статус: {store.get_approval_status_display()}'
            )

        # Предзагружаем все товары одним запросом вместо N запросов в цикле
        product_ids = [item.product_id for item in items_data]
        products_map = {
            p.id: p
            for p in Product.objects.filter(id__in=product_ids, is_active=True)
        }

        # Валидация и создание позиций
        total_amount = Decimal('0')
        items_to_create = []

        for item_data in items_data:
            product = products_map.get(item_data.product_id)
            if product is None:
                raise ValidationError(
                    f'Товар с ID {item_data.product_id} не найден или неактивен'
                )

            quantity = Decimal(str(item_data.quantity))

            # Валидация весовых товаров
            if product.is_weight_based:
                cls._validate_weight_quantity(product, quantity)

            # Рассчитываем бонус для штучных бонусных товаров.
            # Формула: за каждые 50 платных → 4 бонуса (milestone),
            # плюс внутри каждого отрезка 50 за каждые 20 → 1 бонус.
            # Примеры: 20→1, 40→2, 50→4, 70→5, 90→6, 100→8
            # quantity = ИТОГО (платные + бонусные включены)
            # 75 итого → бонус=5 → платных=70, списывается 75 со склада
            bonus_quantity = Decimal('0')
            paid_quantity = quantity
            if product.is_bonus and not product.is_weight_based:
                qty_int = int(quantity)
                # quantity = ИТОГО (платные + бонусные).
                # Формула применяется к платному кол-ву, поэтому ищем paid
                # бинарным поиском: paid + formula(paid) == qty_int.
                lo, hi = 0, qty_int
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    b = 4 * (mid // 50) + (mid % 50) // 20
                    if mid + b <= qty_int:
                        lo = mid
                    else:
                        hi = mid - 1
                paid_int = lo
                bonus_count = qty_int - paid_int
                bonus_quantity = Decimal(str(bonus_count))
                paid_quantity = Decimal(str(paid_int))

            # Проверка наличия на складе (total = quantity)
            if product.stock_quantity < quantity:
                raise ValidationError(
                    f'Недостаточно товара "{product.name}" на складе. '
                    f'Доступно: {product.stock_quantity}, запрошено: {quantity}'
                )

            # Цена считается только с платной части
            price = item_data.price or product.final_price
            item_total = paid_quantity * price

            items_to_create.append({
                'product': product,
                'quantity': paid_quantity,
                'price': price,
                'total': item_total,
                'is_bonus': False,
            })

            # Добавляем бонусные позиции
            if bonus_quantity > 0:
                items_to_create.append({
                    'product': product,
                    'quantity': bonus_quantity,
                    'price': price,
                    'total': Decimal('0'),
                    'is_bonus': True,
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

        # Создание позиций одним bulk_create вместо N отдельных INSERT
        StoreOrderItem.objects.bulk_create([
            StoreOrderItem(
                order=order,
                product=item['product'],
                quantity=item['quantity'],
                price=item['price'],
                total=item['total'],
                is_bonus=item['is_bonus'],
            )
            for item in items_to_create
        ])

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
        # Минимум 0.1 кг, шаг 0.1 кг
        min_qty = Decimal('0.1')
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
        Одобряет заказ (ТЗ v3.0).

        ИЗМЕНЕНИЯ v3.0:
        - Товары резервируются из PartnerInventory (не со склада админа!)
        - Партнёр должен быть указан или вызывающий должен быть партнёром
        - available_quantity проверяется перед резервированием

        Args:
            order: Заказ
            admin_user: Пользователь (админ или партнёр)
            assign_to_partner: Партнёр (опционально, если вызывает админ)

        Returns:
            StoreOrder
        """
        from stores.services import PartnerInventoryService

        # Lock the order row to prevent double-approve race condition
        order = StoreOrder.objects.select_for_update().get(pk=order.pk)

        if order.status != StoreOrderStatus.PENDING:
            raise ValidationError(
                f'Невозможно одобрить заказ в статусе "{order.get_status_display()}"'
            )

        # Определяем партнёра
        partner = None
        if admin_user.role == 'partner':
            # Партнёр сам принимает заказ
            partner = admin_user
        elif assign_to_partner:
            # Админ назначил партнёра
            if assign_to_partner.role != 'partner':
                raise ValidationError("Можно назначить только партнёра")
            partner = assign_to_partner
        else:
            raise ValidationError(
                "Необходимо указать партнёра (assign_to_partner_id) "
                "или вызывать от имени партнёра"
            )

        # Проверка наличия товаров ОТКЛЮЧЕНА для возможности принятия заказа с нехваткой
        # Пользователь имеет возможность удалить недостающие товары из корзины позже
        # order_by('product_id') обязателен: детерминированный порядок блокировок
        # PartnerInventory предотвращает дедлок при параллельных approve одного партнёра.
        order_items = order.items.select_related('product').order_by('product_id')

        # Резервируем товары в PartnerInventory (с перерасходом если нужно)
        for item in order_items:
            PartnerInventoryService.reserve_quantity(
                partner=partner,
                product=item.product,
                quantity=item.quantity,
                is_bonus=item.is_bonus,
                check_availability=False
            )

        # Изменение статуса
        old_status = order.status
        order.status = StoreOrderStatus.IN_TRANSIT
        order.reviewed_by = admin_user
        order.reviewed_at = timezone.now()
        order.partner = partner

        order.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'partner'])

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=StoreOrderStatus.IN_TRANSIT,
            changed_by=admin_user,
            comment=(
                f'Заказ одобрен. Партнёр: {partner.get_full_name()}. '
                f'Товары зарезервированы в инвентаре партнёра. '
                f'Ожидает подтверждения корзины.'
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

        # Загружаем товары с блокировкой, чтобы исключить TOCTOU при параллельных заказах
        order_items = list(order.items.select_related('product').all())
        product_ids = [item.product_id for item in order_items]
        locked_products = {
            p.id: p
            for p in Product.objects.select_for_update().filter(id__in=product_ids)
        }

        # Проверка наличия на актуальных заблокированных данных
        for item in order_items:
            product = locked_products[item.product_id]
            if product.stock_quantity < item.quantity:
                raise ValidationError(
                    f'Недостаточно товара "{product.name}" на складе. '
                    f'Доступно: {product.stock_quantity}, требуется: {item.quantity}'
                )

        # Уменьшаем остатки атомарно через F()
        for item in order_items:
            new_qty = locked_products[item.product_id].stock_quantity - item.quantity
            Product.objects.filter(pk=item.product_id).update(
                stock_quantity=F('stock_quantity') - item.quantity,
                is_available=new_qty > Decimal('0'),
            )

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

        # Получаем все IN_TRANSIT заказы (list чтобы не делать два SQL вызова)
        orders = list(StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).prefetch_related('items__product__images').order_by('created_at'))

        if not orders:
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
            'orders_count': len(orders),
            'order_ids': [o.id for o in orders],
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

        WORKFLOW v3.0:
        1. Удаляем/изменяем товары в StoreOrderItem
        2. Освобождаем резерв в PartnerInventory при удалении
        3. Пересчитываем суммы заказов
        4. Меняем статус заказов: IN_TRANSIT → ACCEPTED
        5. Списываем товары из PartnerInventory
        6. Добавляем товары в StoreInventory
        7. Создаём долг
        """
        import logging
        logger = logging.getLogger(__name__)
        from stores.services import PartnerInventoryService

        items_to_remove = items_to_remove or []
        items_to_modify = items_to_modify or []

        # Проверка партнёра
        if partner_user.role != 'partner':
            raise ValidationError('Только партнёры могут подтверждать корзину')

        # Получаем IN_TRANSIT заказы.
        # order_by('id') обязателен при select_for_update:
        # без детерминированного порядка блокировки разные транзакции
        # могут захватывать строки в разном порядке → deadlock.
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).order_by('id').select_for_update().prefetch_related('items__product')

        # Материализуем сразу — избегаем двойного SQL (exists + затем цикл)
        orders_materialized = list(orders)
        if not orders_materialized:
            raise ValidationError('Нет заказов для подтверждения')
        orders = orders_materialized

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

                # v3.0: Освобождаем резерв в PartnerInventory
                PartnerInventoryService.release_reserved(
                    partner=partner_user,
                    product=item.product,
                    quantity=item.quantity,
                    is_bonus=item.is_bonus
                )

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
                # Удаляем все позиции — возвращаем весь объём на склад одним UPDATE
                items_list = list(items)
                total_to_return = sum(i.quantity for i in items_list)
                for item in items_list:
                    removed_info.append({
                        'product_id': product_id,
                        'product_name': item.product.name,
                        'quantity': float(item.quantity),
                        'order_id': item.order_id,
                    })
                    # Освобождаем резерв в PartnerInventory
                    PartnerInventoryService.release_reserved(
                        partner=partner_user,
                        product=item.product,
                        quantity=item.quantity,
                        is_bonus=item.is_bonus,
                    )
                items.delete()
                # Атомарный возврат на склад через F() — без race condition
                Product.objects.filter(pk=product_id).update(
                    stock_quantity=F('stock_quantity') + total_to_return
                )
                continue

            # Уменьшаем количество пропорционально или в первом заказе
            difference = current_total - new_quantity
            items_list = list(items)  # Материализуем, чтобы не делать повторные запросы
            first_item = items_list[0]
            product = first_item.product

            if first_item.quantity >= difference:
                # Достаточно уменьшить первую позицию
                old_qty = first_item.quantity
                first_item.quantity -= difference
                first_item.total = first_item.quantity * first_item.price
                first_item.save(update_fields=['quantity', 'total'])

                # Атомарный возврат на склад через F() — без race condition
                Product.objects.filter(pk=product_id).update(
                    stock_quantity=F('stock_quantity') + difference
                )

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
                total_returned = Decimal('0')
                for item in items_list:
                    if remaining_to_remove <= 0:
                        break

                    if item.quantity <= remaining_to_remove:
                        # Удаляем полностью
                        remaining_to_remove -= item.quantity
                        total_returned += item.quantity
                        # Освобождаем резерв в PartnerInventory
                        PartnerInventoryService.release_reserved(
                            partner=partner_user,
                            product=item.product,
                            quantity=item.quantity,
                            is_bonus=item.is_bonus,
                        )
                        item.delete()
                    else:
                        # Уменьшаем частично
                        old_qty = item.quantity
                        item.quantity -= remaining_to_remove
                        item.total = item.quantity * item.price
                        item.save(update_fields=['quantity', 'total'])
                        total_returned += remaining_to_remove

                        modified_info.append({
                            'product_id': product_id,
                            'product_name': product.name,
                            'old_quantity': float(old_qty),
                            'new_quantity': float(item.quantity),
                            'order_id': item.order_id,
                        })
                        remaining_to_remove = Decimal('0')

                # Один атомарный UPDATE для всего возвращённого объёма
                if total_returned > 0:
                    Product.objects.filter(pk=product_id).update(
                        stock_quantity=F('stock_quantity') + total_returned
                    )

            logger.info(
                f"Изменено количество товара {product_id} в корзине магазина {store.id}: "
                f"{current_total} → {new_quantity}"
            )

        # =====================================================================
        # 3. ПЕРЕСЧЁТ СУММ ЗАКАЗОВ
        # =====================================================================
        # Используем aggregate вместо Python-цикла — один SQL-запрос на заказ
        # вместо N+1. refresh_from_db() здесь не нужен: мы только что сами
        # изменили items через ORM и кэш prefetch уже не актуален.
        from django.db.models import Sum as _Sum
        order_ids = [o.id for o in orders]
        totals_by_order = dict(
            StoreOrderItem.objects.filter(order_id__in=order_ids)
            .values('order_id')
            .annotate(s=_Sum('total'))
            .values_list('order_id', 's')
        )
        for order in orders:
            new_total = totals_by_order.get(order.id) or Decimal('0')
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

        # Распределяем предоплату по заказам пропорционально.
        # Остаток после округления кладём в последний заказ, чтобы сумма
        # распределённых предоплат точно равнялась prepayment_amount.
        remaining_prepayment = prepayment_amount

        # =====================================================================
        # 5. ПОДТВЕРЖДЕНИЕ ЗАКАЗОВ И ПЕРЕНОС В ИНВЕНТАРЬ
        # =====================================================================
        confirmed_orders = []
        confirmed_at = timezone.now()  # Одно время для всех заказов корзины
        orders_list = list(orders)  # Материализуем для корректной работы enumerate

        for idx, order in enumerate(orders_list):
            # Рассчитываем предоплату для этого заказа
            if total_amount > 0:
                is_last = (idx == len(orders_list) - 1)
                if is_last:
                    # Последний заказ получает остаток, чтобы избежать
                    # накопленной ошибки округления
                    order_prepayment = remaining_prepayment
                else:
                    order_prepayment = (
                        (order.total_amount / total_amount) * prepayment_amount
                    ).quantize(Decimal('0.01'))
                    remaining_prepayment -= order_prepayment
            else:
                order_prepayment = Decimal('0')

            order_debt = order.total_amount - order_prepayment

            # Обновляем заказ
            old_status = order.status
            order.status = StoreOrderStatus.ACCEPTED
            order.partner = partner_user
            order.confirmed_by = partner_user
            order.confirmed_at = confirmed_at
            order.prepayment_amount = order_prepayment
            order.debt_amount = order_debt

            order.save(update_fields=[
                'status', 'partner', 'confirmed_by', 'confirmed_at',
                'prepayment_amount', 'debt_amount'
            ])

            # v3.0: Списываем из PartnerInventory и переносим в StoreInventory
            for item in order.items.all():
                # Завершаем резервацию (списываем и quantity и reserved_quantity)
                PartnerInventoryService.complete_reservation(
                    partner=partner_user,
                    product=item.product,
                    quantity=item.quantity,
                    is_bonus=item.is_bonus
                )
                # Добавляем в инвентарь магазина (is_bonus важен для корректного paid_count/bonus_count)
                StoreInventoryService.add_to_inventory(
                    store=store,
                    product=item.product,
                    quantity=item.quantity,
                    is_bonus=item.is_bonus,
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
        # Используем F() expression вместо read-modify-write для исключения race condition
        Store.objects.filter(pk=store.pk).update(debt=F('debt') + total_debt)
        store = Store.objects.get(pk=store.pk)

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
        
        # Защита от двойной отправки (60 сек окно)
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(seconds=60)
        duplicate = PartnerRequest.objects.filter(
            partner=partner,
            request_type=request_type,
            status=PartnerRequestStatus.PENDING,
            created_at__gte=cutoff
        ).first()
        if duplicate:
            logger.info(
                f"Дубликат запроса партнёра (60с окно) | "
                f"Partner: {partner.id} | Type: {request_type} | "
                f"Existing: #{duplicate.id}"
            )
            return duplicate
        
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
        
        # Предварительно загружаем все товары одним запросом
        product_ids = [item_data.get('product') for item_data in items]
        products_map = {
            p.id: p for p in Product.objects.filter(pk__in=product_ids)
        }

        items_to_create = []

        # Создаём позиции запроса
        for item_data in items:
            product_id = item_data.get('product')
            quantity = Decimal(str(item_data.get('quantity', 0)))
            weight = item_data.get('weight')
            is_bonus = item_data.get('is_bonus', False)

            product = products_map.get(product_id)
            if product is None:
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
                    quantity=effective_quantity,
                    is_bonus=is_bonus
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
                    quantity=effective_quantity,
                    is_bonus=is_bonus
                )
            
            # Собираем позицию для bulk_create
            # Для весовых: quantity = weight (для правильного расчёта суммы)
            items_to_create.append(PartnerRequestItem(
                request=request,
                product=product,
                quantity=effective_quantity,
                weight=weight if product.is_weight_based else None,
                price_at_request=product.final_price,
                is_bonus=is_bonus,
            ))

        PartnerRequestItem.objects.bulk_create(items_to_create)

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
            items_list = list(items)
            product_ids = [item.product_id for item in items_list]

            # Блокируем строки продуктов для исключения TOCTOU race condition:
            # между проверкой наличия и списанием другая транзакция не изменит сток.
            locked_products = {
                p.id: p
                for p in Product.objects.select_for_update().filter(id__in=product_ids)
            }

            # Проверяем наличие ВСЕХ товаров на заблокированных данных
            for item in items_list:
                product = locked_products[item.product_id]
                if product.stock_quantity < item.quantity:
                    raise ValidationError(
                        f'Недостаточно товара "{product.name}" на складе. '
                        f'Доступно: {product.stock_quantity}, запрошено: {item.quantity}'
                    )

            # Обрабатываем товары — атомарное списание через F() без stale read
            for item in items_list:
                product = locked_products[item.product_id]
                quantity = item.quantity

                new_qty = product.stock_quantity - quantity
                Product.objects.filter(pk=product.pk).update(
                    stock_quantity=F('stock_quantity') - quantity,
                    is_available=new_qty > Decimal('0'),
                )

                # Добавляем в инвентарь партнёра
                PartnerInventoryService.add_to_inventory(
                    partner=partner,
                    product=product,
                    quantity=quantity,
                    is_bonus=item.is_bonus,
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

                # ИСПРАВЛЕНИЕ: при создании возврата товары были зарезервированы
                # через reserve_quantity(), поэтому available_quantity = 0.
                # remove_from_inventory() проверяет available_quantity → ошибка
                # "Доступно: 0.000, запрошено: N.000".
                # complete_reservation() проверяет reserved_quantity и атомарно
                # уменьшает и quantity, и reserved_quantity — корректный путь.
                PartnerInventoryService.complete_reservation(
                    partner=partner,
                    product=product,
                    quantity=quantity,
                    is_bonus=item.is_bonus
                )

                # Атомарное увеличение склада через F() без stale read
                Product.objects.filter(pk=product.pk).update(
                    stock_quantity=F('stock_quantity') + quantity,
                    is_available=True,
                )
                
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
                        quantity=item.quantity,
                        is_bonus=item.is_bonus
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
                        quantity=item.quantity,
                        is_bonus=item.is_bonus
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
        ).select_related('product', 'reviewed_by').prefetch_related('items__product').order_by('-created_at')
        
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
            status=PartnerRequestStatus.PENDING,
        ).select_related('partner', 'product').prefetch_related('items__product').order_by('created_at')


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
        notes: str = '',
        idempotency_key: Optional[str] = None
    ) -> StoreOrder:
        """
        Создать ручной заказ партнёром.
        
        Args:
            partner: Партнёр
            store: Магазин
            items: Список товаров
            prepayment_amount: Сумма предоплаты
            notes: Примечания
            idempotency_key: Ключ идемпотентности (защита от двойной отправки)
            
        Returns:
            StoreOrder
            
        Raises:
            ValidationError: При ошибках
        """
        from stores.services import PartnerInventoryService
        import logging
        logger = logging.getLogger(__name__)
        
        # Защита от двойной отправки (idempotency_key)
        if idempotency_key:
            existing = StoreOrder.objects.filter(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                logger.info(f"Дубликат ручного заказа по idempotency_key: {idempotency_key}")
                return existing
        else:
            # Fallback: проверка дубликата по partner + store + время (60 сек)
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(seconds=60)
            duplicate = StoreOrder.objects.filter(
                partner=partner,
                store=store,
                order_type='manual',
                created_at__gte=cutoff
            ).first()
            if duplicate:
                logger.info(
                    f"Дубликат ручного заказа (60с окно) | "
                    f"Partner: {partner.id} | Store: {store.id} | "
                    f"Existing order: #{duplicate.id}"
                )
                return duplicate
        
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
            notes=notes,
            idempotency_key=idempotency_key or None
        )
        
        total_amount = Decimal('0')

        # Предварительно загружаем все товары одним запросом
        product_ids = [item_data.product_id for item_data in items]
        products_map = {
            p.id: p for p in Product.objects.filter(pk__in=product_ids)
        }

        order_items_to_create = []

        # Предварительно загружаем доп цены если нужны
        ap_ids = [item_data.additional_price_id for item_data in items if item_data.additional_price_id]
        if ap_ids:
            from products.models import AdditionalPrice
            ap_map = {
                ap.id: ap for ap in AdditionalPrice.objects.filter(pk__in=ap_ids, is_active=True)
            }
        else:
            ap_map = {}

        # Обрабатываем товары
        for item_data in items:
            product = products_map.get(item_data.product_id)
            if product is None:
                raise ValidationError(f'Товар с ID {item_data.product_id} не найден')

            # Валидация доп цены
            if item_data.additional_price_id:
                additional_price = ap_map.get(item_data.additional_price_id)
                if not additional_price:
                    raise ValidationError(
                        f'Доп цена с ID {item_data.additional_price_id} не найдена или не активна'
                    )
                if additional_price.product_id != product.id:
                    raise ValidationError(
                        f'Доп цена "{additional_price.name}" не принадлежит товару "{product.name}"'
                    )
                if item_data.is_bonus:
                    raise ValidationError(
                        f'Товар с доп ценой не может быть бонусным ({product.name})'
                    )

            quantity = item_data.quantity
            is_bonus_provided = item_data.is_bonus

            # 1. Если это явный бонусный товар (выбран партнёром как бонус)
            if is_bonus_provided:
                # Проверяем наличие в бонусном инвентаре
                has_inventory = PartnerInventoryService.check_availability(
                    partner=partner,
                    product=product,
                    quantity=quantity,
                    is_bonus=True
                )
                if not has_inventory:
                    raise ValidationError(
                        f'Недостаточно бонусного товара {product.name} в инвентаре партнёра'
                    )
                
                # Списываем из бонусного инвентарья
                PartnerInventoryService.remove_from_inventory(
                    partner=partner,
                    product=product,
                    quantity=quantity,
                    is_bonus=True
                )
                
                # Добавляем в инвентарь магазина как бонусный товар
                StoreInventoryService.add_to_inventory(
                    store=store,
                    product=product,
                    quantity=quantity,
                    is_bonus=True,
                )
                
                # Собираем позицию заказа (бонус)
                order_items_to_create.append(StoreOrderItem(
                    order=order,
                    product=product,
                    quantity=quantity,
                    price=item_data.price or product.final_price,  # Цена справочная, total=0
                    total=Decimal('0'),
                    is_bonus=True,
                ))
                
            else:
                # 2. Если это обычный товар
                
                # quantity = ИТОГО везёт партнёр (платные + бонусные включены)
                # Бонус рассчитывается ОТ этого количества и уже входит в него:
                # 54 итого → 4 бонуса → 50 платных (списывается 54 из инвентаря)
                bonus_quantity = Decimal('0')
                paid_quantity = quantity
                if product.is_bonus and not product.is_weight_based:
                    qty_int = int(quantity)
                    # quantity = ИТОГО (платные + бонусные).
                    # Формула применяется к платному кол-ву, поэтому ищем paid
                    # бинарным поиском: paid + formula(paid) == qty_int.
                    lo, hi = 0, qty_int
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        b = 4 * (mid // 50) + (mid % 50) // 20
                        if mid + b <= qty_int:
                            lo = mid
                        else:
                            hi = mid - 1
                    paid_int = lo
                    bonus_count = qty_int - paid_int
                    bonus_quantity = Decimal(str(bonus_count))
                    paid_quantity = Decimal(str(paid_int))

                # Проверяем наличие у партнёра (ровно столько сколько везёт)
                has_inventory = PartnerInventoryService.check_availability(
                    partner=partner,
                    product=product,
                    quantity=quantity,
                    is_bonus=False
                )
                if not has_inventory:
                    raise ValidationError(
                        f'Недостаточно товара {product.name} в инвентаре партнёра'
                    )

                # Списываем из инвентаря ровно столько сколько везёт (quantity)
                PartnerInventoryService.remove_from_inventory(
                    partner=partner,
                    product=product,
                    quantity=quantity,
                    is_bonus=False
                )

                # Добавляем в инвентарь магазина
                StoreInventoryService.add_to_inventory(
                    store=store,
                    product=product,
                    quantity=paid_quantity,
                    is_bonus=False,
                )
                if bonus_quantity > 0:
                    StoreInventoryService.add_to_inventory(
                        store=store,
                        product=product,
                        quantity=bonus_quantity,
                        is_bonus=True,
                    )

                # Собираем позицию заказа (только платная часть считается в сумму)
                # Приоритет: доп цена > ручная цена > final_price
                if item_data.additional_price_id:
                    price = ap_map[item_data.additional_price_id].price
                else:
                    price = item_data.price or product.final_price
                item_total = price * paid_quantity

                order_items_to_create.append(StoreOrderItem(
                    order=order,
                    product=product,
                    quantity=paid_quantity,
                    price=price,
                    total=item_total,
                    is_bonus=False,
                ))

                # Собираем бонусную позицию
                if bonus_quantity > 0:
                    order_items_to_create.append(StoreOrderItem(
                        order=order,
                        product=product,
                        quantity=bonus_quantity,
                        price=price,
                        total=Decimal('0'),
                        is_bonus=True,
                    ))

                total_amount += item_total

        StoreOrderItem.objects.bulk_create(order_items_to_create)

        # Обновляем заказ (округляем до 2 знаков после запятой)
        total_amount = total_amount.quantize(Decimal('0.01'))
        if prepayment_amount > total_amount:
            raise ValidationError('Предоплата не может превышать сумму заказа')
        debt_amount = (total_amount - prepayment_amount).quantize(Decimal('0.01'))
        order.total_amount = total_amount
        order.debt_amount = debt_amount
        order.save(update_fields=['total_amount', 'debt_amount'])
        
        # Обновляем долг магазина атомарно через F() — без race condition
        Store.objects.filter(pk=store.pk).update(debt=F('debt') + debt_amount)
        store = Store.objects.get(pk=store.pk)
        
        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status='created',  # Для нового заказа используем 'created'
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
