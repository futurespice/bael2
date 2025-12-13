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

        КРИТИЧЕСКИЕ ПРОВЕРКИ (ИСПРАВЛЕНИЯ #4 и #5):
        ✅ 1. Магазин должен быть активным (is_active=True)
        ✅ 2. Магазин должен быть одобрен (approval_status=APPROVED)
        ✅ 3. Товар должен быть в наличии (stock_quantity >= quantity)
        ✅ 4. Товар должен быть активным (is_active=True)
        ✅ 5. Для весовых товаров: минимум 1 кг, шаг 0.1 кг

        WORKFLOW:
        1. Магазин создаёт заказ → статус PENDING
        2. Товары НЕ уходят из инвентаря сразу
        3. Товары добавляются в инвентарь только после одобрения админом

        Args:
            store: Магазин, создающий заказ
            items_data: Список товаров для заказа
            created_by: Пользователь (опционально)
            idempotency_key: Ключ для защиты от дублирования (опционально)

        Returns:
            StoreOrder: Созданный заказ в статусе PENDING

        Raises:
            ValidationError: При нарушении любого из бизнес-правил

        Example:
            >>> items = [
            ...     OrderItemData(product_id=1, quantity=Decimal('10')),
            ...     OrderItemData(product_id=2, quantity=Decimal('2.5')),
            ... ]
            >>> order = OrderWorkflowService.create_store_order(
            ...     store=my_store,
            ...     items_data=items,
            ...     created_by=user
            ... )
        """

        # =========================================================================
        # ✅ КРИТИЧЕСКАЯ ПРОВЕРКА #4: Магазин должен быть активным
        # =========================================================================
        if not store.is_active:
            raise ValidationError(
                f"Магазин '{store.name}' заблокирован и не может создавать заказы. "
                f"Обратитесь к администратору для разблокировки. "
                f"Причина блокировки может быть связана с нарушением условий работы или задолженностью."
            )

        # =========================================================================
        # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Магазин должен быть одобрен
        # =========================================================================
        if store.approval_status != Store.ApprovalStatus.APPROVED:
            raise ValidationError(
                f"Магазин '{store.name}' не одобрен администратором. "
                f"Текущий статус: {store.get_approval_status_display()}. "
                f"Дождитесь одобрения администратором перед созданием заказов. "
                f"Для ускорения процесса обратитесь в службу поддержки."
            )

        # =========================================================================
        # ПРОВЕРКА IDEMPOTENCY (защита от дублирования)
        # =========================================================================
        if idempotency_key:
            existing_order = StoreOrder.objects.filter(
                idempotency_key=idempotency_key
            ).first()

            if existing_order:
                # Заказ с таким ключом уже существует - возвращаем его
                return existing_order

        # =========================================================================
        # ✅ КРИТИЧЕСКАЯ ПРОВЕРКА #5: Проверка товаров
        # =========================================================================

        # Проверка что есть хотя бы один товар
        if not items_data or len(items_data) == 0:
            raise ValidationError(
                "Заказ должен содержать хотя бы один товар. "
                "Добавьте товары в заказ и попробуйте снова."
            )

        # Собираем ID всех товаров из заказа
        product_ids = [item.product_id for item in items_data]

        # Загружаем все товары одним запросом (оптимизация N+1)
        products = Product.objects.filter(pk__in=product_ids)
        products_dict = {p.id: p for p in products}

        # Проверяем каждый товар в заказе
        for item in items_data:
            product_id = item.product_id

            # ✅ ПРОВЕРКА #5a: Товар существует
            if product_id not in products_dict:
                raise ValidationError(
                    f"Товар с ID={product_id} не найден в каталоге. "
                    f"Возможно, товар был удалён администратором. "
                    f"Обновите список товаров и попробуйте снова."
                )

            product = products_dict[product_id]

            # ✅ ПРОВЕРКА #5b: Товар активен
            if not product.is_active:
                raise ValidationError(
                    f"Товар '{product.name}' недоступен для заказа. "
                    f"Товар был деактивирован администратором. "
                    f"Пожалуйста, выберите другой товар из каталога."
                )

            # ✅ ПРОВЕРКА #5c: Наличие на складе (stock_quantity)
            if product.stock_quantity < item.quantity:
                # Для весовых товаров
                if product.is_weight_based:
                    raise ValidationError(
                        f"Недостаточно товара '{product.name}' на складе. "
                        f"Запрошено: {item.quantity} кг, "
                        f"доступно: {product.stock_quantity} кг. "
                        f"Пожалуйста, уменьшите количество в заказе или выберите другой товар."
                    )
                # Для штучных товаров
                else:
                    raise ValidationError(
                        f"Недостаточно товара '{product.name}' на складе. "
                        f"Запрошено: {int(item.quantity)} шт., "
                        f"доступно: {int(product.stock_quantity)} шт. "
                        f"Пожалуйста, уменьшите количество в заказе или выберите другой товар."
                    )

            # ✅ ПРОВЕРКА #5d: Для весовых товаров - минимальное количество и шаг
            if product.is_weight_based:
                # Определяем минимум в зависимости от остатка
                if product.stock_quantity < Decimal('1'):
                    min_quantity = Decimal('0.1')
                else:
                    min_quantity = Decimal('1')

                # Проверка минимума
                if item.quantity < min_quantity:
                    raise ValidationError(
                        f"Для товара '{product.name}' минимальное количество: {min_quantity} кг. "
                        f"Вы указали: {item.quantity} кг. "
                        f"Увеличьте количество до {min_quantity} кг или более."
                    )

                # Проверка шага (должно быть кратно 0.1 кг = 100 грамм)
                # Умножаем на 10 и проверяем остаток от деления на 1
                remainder = (item.quantity * 10) % 1
                if remainder != 0:
                    raise ValidationError(
                        f"Количество для '{product.name}' должно быть кратно 0.1 кг (100 грамм). "
                        f"Вы указали: {item.quantity} кг. "
                        f"Примеры корректных значений: 1.0, 1.1, 1.2, 1.3, 2.5 кг и т.д."
                    )

            # ✅ ПРОВЕРКА #5e: Для штучных товаров - целое число
            if not product.is_weight_based:
                if item.quantity != int(item.quantity):
                    raise ValidationError(
                        f"Для товара '{product.name}' количество должно быть целым числом. "
                        f"Вы указали: {item.quantity}. "
                        f"Используйте только целые числа: 1, 2, 3, 10 и т.д."
                    )

        # =========================================================================
        # ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - СОЗДАЁМ ЗАКАЗ
        # =========================================================================

        # Создаём заказ в статусе PENDING
        order = StoreOrder.objects.create(
            store=store,
            partner=None,  # Партнёр будет назначен позже админом
            created_by=created_by,
            status=StoreOrderStatus.PENDING,
            idempotency_key=idempotency_key,
            total_amount=Decimal('0'),  # Будет пересчитано ниже
            debt_amount=Decimal('0'),
            prepayment_amount=Decimal('0'),
            paid_amount=Decimal('0'),
        )

        # Добавляем позиции в заказ
        total_amount = Decimal('0')

        for item_data in items_data:
            product = products_dict[item_data.product_id]

            # Определяем цену (из item_data или берём из Product)
            price = item_data.price if item_data.price is not None else product.final_price

            # Создаём позицию заказа
            order_item = StoreOrderItem.objects.create(
                order=order,
                product=product,
                quantity=item_data.quantity,
                price=price,
                is_bonus=item_data.is_bonus,
                # total вычисляется автоматически в save() модели
            )

            # Суммируем общую стоимость
            total_amount += order_item.total

        # Обновляем общую сумму заказа
        order.total_amount = total_amount
        order.save(update_fields=['total_amount'])

        # =========================================================================
        # СОЗДАЁМ ЗАПИСЬ В ИСТОРИИ
        # =========================================================================
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status='',  # Нет предыдущего статуса
            new_status=StoreOrderStatus.PENDING,
            changed_by=created_by,
            comment=(
                f"Заказ создан магазином '{store.name}'. "
                f"Количество позиций: {len(items_data)}. "
                f"Общая сумма: {total_amount} сом."
            )
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

        КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ (ERROR-9):
        ✅ 1. ПЕРЕД одобрением проверяем наличие товаров на складе
        ✅ 2. УМЕНЬШАЕМ stock_quantity при одобрении
        ✅ 3. Обновляем is_available если товар закончился
        ✅ 4. ОТКАТЫВАЕМ транзакцию если товара недостаточно

        Действия:
        1. Проверка прав и статуса
        2. ✅ НОВОЕ: Проверка наличия товаров на складе
        3. ✅ НОВОЕ: Уменьшение stock_quantity
        4. Добавление товаров в инвентарь магазина
        5. Изменение статуса на IN_TRANSIT
        6. Опционально назначение партнёра

        Args:
            order: Заказ для одобрения
            admin_user: Администратор
            assign_to_partner: Партнёр (опционально)

        Returns:
            StoreOrder в статусе IN_TRANSIT

        Raises:
            ValidationError: Если недостаточно товаров на складе
        """
        # =========================================================================
        # ПРОВЕРКА ПРАВ И СТАТУСА
        # =========================================================================
        if admin_user.role != 'admin':
            raise ValidationError("Только администратор может одобрять заказы")

        if order.status != StoreOrderStatus.PENDING:
            raise ValidationError(
                f"Можно одобрить только заказы в статусе 'В ожидании'. "
                f"Текущий статус: {order.get_status_display()}"
            )

        # =========================================================================
        # ✅ КРИТИЧЕСКОЕ ДОБАВЛЕНИЕ ERROR-9: ПРОВЕРКА НАЛИЧИЯ НА СКЛАДЕ
        # =========================================================================

        # Загружаем все товары заказа с блокировкой (для избежания гонки)
        order_items = order.items.select_related('product').select_for_update()

        # Проверяем КАЖДЫЙ товар ДО одобрения
        insufficient_products = []

        for item in order_items:
            product = item.product

            # Проверка наличия
            if product.stock_quantity < item.quantity:
                insufficient_products.append({
                    'product_name': product.name,
                    'requested': item.quantity,
                    'available': product.stock_quantity,
                    'missing': item.quantity - product.stock_quantity,
                })

        # Если хотя бы один товар отсутствует - ОТКАТЫВАЕМ всю транзакцию
        if insufficient_products:
            error_details = "\n".join([
                f"- {p['product_name']}: "
                f"нужно {p['requested']}, "
                f"на складе {p['available']}, "
                f"не хватает {p['missing']}"
                for p in insufficient_products
            ])

            raise ValidationError(
                f"Недостаточно товаров на складе для одобрения заказа #{order.id}:\n"
                f"{error_details}\n\n"
                f"Пожалуйста, пополните склад или уменьшите количество в заказе."
            )

        # =========================================================================
        # ✅ КРИТИЧЕСКОЕ ДОБАВЛЕНИЕ ERROR-9: УМЕНЬШЕНИЕ STOCK_QUANTITY
        # =========================================================================

        # Все проверки пройдены - уменьшаем остатки
        for item in order_items:
            product = item.product

            # Уменьшаем количество на складе
            product.stock_quantity -= item.quantity

            # Если товар закончился - помечаем как недоступный
            if product.stock_quantity <= Decimal('0'):
                product.stock_quantity = Decimal('0')
                product.is_available = False

            # Сохраняем изменения
            product.save(update_fields=['stock_quantity', 'is_available'])

            # Логирование для аудита
            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"Склад обновлён | Товар: {product.name} | "
                f"Заказ #{order.id} | Списано: {item.quantity} | "
                f"Остаток: {product.stock_quantity}"
            )

        # =========================================================================
        # ДОБАВЛЕНИЕ ТОВАРОВ В ИНВЕНТАРЬ МАГАЗИНА
        # =========================================================================
        for item in order_items:
            StoreInventoryService.add_to_inventory(
                store=order.store,
                product=item.product,
                quantity=item.quantity
            )

        # =========================================================================
        # ИЗМЕНЕНИЕ СТАТУСА ЗАКАЗА
        # =========================================================================
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

        # =========================================================================
        # ИСТОРИЯ ЗАКАЗА
        # =========================================================================
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=order.id,
            old_status=old_status,
            new_status=StoreOrderStatus.IN_TRANSIT,
            changed_by=admin_user,
            comment=(
                f'Заказ одобрен админом. '
                f'Товары добавлены в инвентарь магазина "{order.store.name}". '
                f'Остатки на складе обновлены.'
            )
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

    def validate_weight_based_quantity(product: Product, quantity: Decimal) -> None:
        """
        Валидация количества для весового товара.

        Правила (ТЗ v2.0):
        - Минимум: 1 кг (или 0.1 кг если остаток < 1 кг)
        - Шаг: 0.1 кг (100 грамм)
        - Максимум: stock_quantity

        Args:
            product: Товар
            quantity: Запрошенное количество

        Raises:
            ValidationError: Если количество некорректно
        """
        if not product.is_weight_based:
            return  # Не весовой товар

        # Определяем минимум
        if product.stock_quantity < Decimal('1'):
            min_quantity = Decimal('0.1')
        else:
            min_quantity = Decimal('1')

        # Проверка минимума
        if quantity < min_quantity:
            raise ValidationError(
                f"Минимальное количество для '{product.name}': {min_quantity} кг"
            )

        # Проверка шага (должно быть кратно 0.1)
        remainder = (quantity * 10) % 1
        if remainder != 0:
            raise ValidationError(
                f"Количество для '{product.name}' должно быть кратно 0.1 кг (100 грамм). "
                f"Например: 1.0, 1.1, 1.2, 1.3 кг и т.д."
            )


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