# apps/stores/services.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum, Count, Q
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import date

from .models import (
    Store, StoreSelection,
    StoreProductRequest, StoreRequest, StoreRequestItem,
    StoreInventory, PartnerInventory
)
from products.models import Product, StoreProductCounter, BonusHistory


class StoreProfileService:
    """
    Сервис для работы с профилем магазина.
    Обеспечивает CRUD операции после выбора магазина (StoreSelection).
    """

    @staticmethod
    def get_current_store(user) -> Optional[Store]:
        """
        Получить текущий выбранный магазин пользователя.
        Возвращает последний выбранный магазин.
        """
        selection = StoreSelection.objects.filter(
            user=user
        ).select_related('store', 'store__region', 'store__city').order_by('-selected_at').first()

        return selection.store if selection else None

    @staticmethod
    def get_store_profile(user) -> Optional[Store]:
        """
        Получить профиль текущего магазина с prefetch для статистики.
        """
        store = StoreProfileService.get_current_store(user)
        if not store:
            return None

        # Prefetch связанные данные для оптимизации
        return Store.objects.select_related(
            'region', 'city', 'created_by'
        ).prefetch_related(
            'orders', 'product_requests', 'requests'
        ).get(pk=store.pk)

    @staticmethod
    @transaction.atomic
    def update_store_profile(user, data: Dict[str, Any]) -> Store:
        """
        Обновить профиль магазина.
        Разрешено: name, owner_name, phone, region, city, address, latitude, longitude.
        Запрещено: inn (по ТЗ).
        """
        store = StoreProfileService.get_current_store(user)
        if not store:
            raise ValidationError('Магазин не выбран. Сначала выберите магазин.')

        # Проверка статуса магазина
        if not store.is_active:
            raise ValidationError('Магазин заморожен. Редактирование недоступно.')

        if store.approval_status != 'approved':
            raise ValidationError('Магазин не одобрен. Редактирование недоступно.')

        # Блокируем запись для обновления
        store = Store.objects.select_for_update().get(pk=store.pk)

        # Обновляем разрешённые поля
        allowed_fields = ['name', 'owner_name', 'phone', 'region', 'city',
                          'address', 'latitude', 'longitude']

        for field in allowed_fields:
            if field in data:
                setattr(store, field, data[field])

        store.full_clean()  # Валидация модели
        store.save()

        return store

    @staticmethod
    def get_store_statistics(store: Store, date_from: date = None, date_to: date = None) -> Dict[str, Any]:
        """
        Получить статистику магазина за период.
        """
        from orders.models import StoreOrder, StoreOrderItem

        orders_qs = StoreOrder.objects.filter(store=store)

        if date_from:
            orders_qs = orders_qs.filter(created_at__date__gte=date_from)
        if date_to:
            orders_qs = orders_qs.filter(created_at__date__lte=date_to)

        # Агрегация
        stats = orders_qs.aggregate(
            total_orders=Count('id'),
            total_amount=Sum('total_amount'),
            total_debt=Sum('debt_amount'),
            total_paid=Sum('paid_amount')
        )

        # Бонусы
        bonus_items = StoreOrderItem.objects.filter(
            order__store=store,
            is_bonus=True
        )
        if date_from:
            bonus_items = bonus_items.filter(order__created_at__date__gte=date_from)
        if date_to:
            bonus_items = bonus_items.filter(order__created_at__date__lte=date_to)

        bonus_stats = bonus_items.aggregate(
            bonus_count=Count('id'),
            bonus_quantity=Sum('quantity')
        )

        return {
            'total_orders': stats['total_orders'] or 0,
            'total_amount': stats['total_amount'] or Decimal('0'),
            'total_debt': stats['total_debt'] or Decimal('0'),
            'total_paid': stats['total_paid'] or Decimal('0'),
            'outstanding_debt': store.debt,
            'bonus_count': bonus_stats['bonus_count'] or 0,
            'bonus_quantity': bonus_stats['bonus_quantity'] or Decimal('0'),
            'wishlist_items': store.product_requests.count()
        }


class StoreRequestService:
    """Сервис работы с запросами магазинов (wishlist)"""

    @staticmethod
    def get_current_store(user) -> Optional[Store]:
        """Helper: получить текущий магазин пользователя"""
        return StoreProfileService.get_current_store(user)

    @staticmethod
    @transaction.atomic
    def add_to_wishlist(user, product: Product, quantity: Decimal) -> StoreProductRequest:
        """
        Добавить товар в wishlist магазина.
        Если товар уже есть - обновляет количество.
        """
        store = StoreRequestService.get_current_store(user)
        if not store:
            raise ValidationError('Магазин не выбран.')

        if not store.is_active:
            raise ValidationError('Магазин заморожен. Операции недоступны.')

        if store.approval_status != 'approved':
            raise ValidationError('Магазин не одобрен.')

        # Валидация количества для весовых товаров
        if product.is_weight_based:
            if quantity < Decimal('0.1'):
                raise ValidationError('Минимальное количество для весового товара: 0.1 кг')
        else:
            if quantity < 1 or quantity != int(quantity):
                raise ValidationError('Для штучного товара количество должно быть целым числом >= 1')

        product_request, created = StoreProductRequest.objects.update_or_create(
            store=store,
            product=product,
            defaults={'quantity': quantity}
        )

        return product_request

    @staticmethod
    @transaction.atomic
    def remove_from_wishlist(user, product: Product) -> bool:
        """
        Удалить товар из wishlist магазина.
        Возвращает True если удалено, False если не найдено.
        """
        store = StoreRequestService.get_current_store(user)
        if not store:
            raise ValidationError('Магазин не выбран.')

        deleted_count, _ = StoreProductRequest.objects.filter(
            store=store,
            product=product
        ).delete()

        return deleted_count > 0

    @staticmethod
    @transaction.atomic
    def clear_wishlist(user) -> int:
        """
        Очистить весь wishlist магазина.
        Возвращает количество удалённых позиций.
        """
        store = StoreRequestService.get_current_store(user)
        if not store:
            raise ValidationError('Магазин не выбран.')

        deleted_count, _ = StoreProductRequest.objects.filter(store=store).delete()
        return deleted_count

    @staticmethod
    def get_wishlist(user) -> Dict[str, Any]:
        """
        Получить wishlist магазина с итогами.
        """
        store = StoreRequestService.get_current_store(user)
        if not store:
            raise ValidationError('Магазин не выбран.')

        items = StoreProductRequest.objects.filter(
            store=store
        ).select_related('product').order_by('-created_at')

        total_amount = sum(
            item.quantity * item.product.price for item in items
        )
        total_items = items.count()

        return {
            'store_id': store.id,
            'store_name': store.name,
            'items': items,
            'total_amount': total_amount,
            'total_items': total_items
        }

    @staticmethod
    @transaction.atomic
    def create_from_product_requests(store, user, note=None, idempotency_key=None):
        """
        Создание StoreRequest из StoreProductRequest (snapshot wishlist'а).
        С защитой от race condition через idempotency_key.
        """
        # Проверяем idempotency_key
        if idempotency_key:
            existing = StoreRequest.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing

        # Получаем все запросы магазина (wishlist items)
        product_requests = StoreProductRequest.objects.select_for_update().filter(
            store=store
        ).select_related('product')

        if not product_requests.exists():
            raise ValidationError('Wishlist пуст. Добавьте товары.')

        # Создаём новый StoreRequest
        store_request = StoreRequest.objects.create(
            store=store,
            created_by=user,
            note=note or '',
            idempotency_key=idempotency_key
        )

        # Переносим товары в StoreRequestItem
        total_amount = Decimal('0')
        for pr in product_requests:
            # Валидация весовых товаров
            if pr.product.is_weight_based:
                if hasattr(pr.product, 'validate_quantity'):
                    pr.product.validate_quantity(pr.quantity)

            item = StoreRequestItem.objects.create(
                request=store_request,
                product=pr.product,
                quantity=pr.quantity,
                price=pr.product.price
            )
            total_amount += item.quantity * item.price

        # Обновляем общую сумму
        store_request.total_amount = total_amount
        store_request.save(update_fields=['total_amount'])

        # Удаляем временные запросы (wishlist очищается после snapshot)
        product_requests.delete()

        return store_request

    @staticmethod
    @transaction.atomic
    def cancel_item(request: StoreRequest, item_id: int):
        """Отменить позицию в запросе"""
        item = StoreRequestItem.objects.select_for_update().get(
            id=item_id,
            request=request
        )

        if item.is_cancelled:
            raise ValidationError('Позиция уже отменена.')

        item.is_cancelled = True
        item.save(update_fields=['is_cancelled'])

        # Пересчитываем сумму запроса
        active_items = request.items.filter(is_cancelled=False)
        request.total_amount = sum(
            item.quantity * item.price for item in active_items
        )
        request.save(update_fields=['total_amount'])


class InventoryService:
    """Управление инвентарём магазинов и партнёров"""

    @staticmethod
    @transaction.atomic
    def add_to_inventory(store=None, partner=None, product=None, quantity=0):
        """Добавить товар в инвентарь"""
        quantity = Decimal(str(quantity))

        if store:
            inventory, _ = StoreInventory.objects.select_for_update().get_or_create(
                store=store,
                product=product,
                defaults={'quantity': Decimal('0')}
            )
            inventory.quantity += quantity
            inventory.save(update_fields=['quantity'])
            return inventory
        elif partner:
            inventory, _ = PartnerInventory.objects.select_for_update().get_or_create(
                partner=partner,
                product=product,
                defaults={'quantity': Decimal('0')}
            )
            inventory.quantity += quantity
            inventory.save(update_fields=['quantity'])
            return inventory

        raise ValueError("Укажите store или partner")

    @staticmethod
    @transaction.atomic
    def remove_from_inventory(store=None, partner=None, product=None, quantity=0):
        """Списать товар из инвентаря"""
        quantity = Decimal(str(quantity))

        if store:
            inventory = StoreInventory.objects.select_for_update().filter(
                store=store,
                product=product
            ).first()
        elif partner:
            inventory = PartnerInventory.objects.select_for_update().filter(
                partner=partner,
                product=product
            ).first()
        else:
            raise ValueError("Укажите store или partner")

        if not inventory or inventory.quantity < quantity:
            available = inventory.quantity if inventory else Decimal('0')
            raise ValidationError(
                f"Недостаточно товара {product.name}. Доступно: {available}"
            )

        inventory.quantity -= quantity

        if inventory.quantity <= Decimal('0'):
            inventory.delete()
            return None
        else:
            inventory.save(update_fields=['quantity'])
            return inventory

    @staticmethod
    def get_inventory(store=None, partner=None):
        """Получить весь инвентарь"""
        if store:
            return StoreInventory.objects.filter(store=store).select_related('product')
        elif partner:
            return PartnerInventory.objects.filter(partner=partner).select_related('product')
        return []

    @staticmethod
    @transaction.atomic
    def transfer_inventory(from_partner=None, to_store=None,
                           from_store=None, to_partner=None,
                           product=None, quantity=None):
        """
        Универсальный метод переноса инвентаря.
        Поддерживает: partner -> store и store -> partner.
        """
        quantity = Decimal(str(quantity))

        if from_partner and to_store:
            # Партнёр -> Магазин
            InventoryService.remove_from_inventory(
                partner=from_partner, product=product, quantity=quantity
            )
            InventoryService.add_to_inventory(
                store=to_store, product=product, quantity=quantity
            )
        elif from_store and to_partner:
            # Магазин -> Партнёр (возврат)
            InventoryService.remove_from_inventory(
                store=from_store, product=product, quantity=quantity
            )
            InventoryService.add_to_inventory(
                partner=to_partner, product=product, quantity=quantity
            )
        else:
            raise ValueError("Укажите корректные параметры переноса")

    @staticmethod
    def check_partner_stock(partner, product, quantity) -> bool:
        """Проверить наличие товара у партнёра"""
        quantity = Decimal(str(quantity))
        inventory = PartnerInventory.objects.filter(
            partner=partner,
            product=product
        ).first()

        if not inventory:
            return False
        return inventory.quantity >= quantity


class BonusService:
    """
    Сервис бонусов.
    Каждый 21-й товар ВСЕГО бесплатно (не по отдельности для каждого товара).
    Весовые товары НЕ участвуют в бонусах.
    """

    @staticmethod
    @transaction.atomic
    def add_product_to_counter(store, partner, product, quantity: int) -> int:
        """
        Добавить товары в счётчик и проверить бонус.
        Весовые товары не участвуют.
        """
        if product.is_weight_based:
            return 0

        counter, _ = StoreProductCounter.objects.select_for_update().get_or_create(
            store=store,
            partner=partner,
            product=product,
            defaults={
                'total_count': 0,
                'product_count': 0
            }
        )

        counter.total_count += quantity
        counter.product_count += quantity
        counter.save()

        # Проверяем бонус (каждый 21-й)
        bonus_count = 0
        if counter.check_bonus():
            bonus_count = counter.total_count // 21

            BonusHistory.objects.create(
                store=store,
                partner=partner,
                product=product,
                quantity=bonus_count,
                bonus_value=product.price * bonus_count
            )

            from django.utils import timezone
            counter.last_bonus_at = timezone.now()
            counter.save(update_fields=['last_bonus_at'])

        return bonus_count

    @staticmethod
    def get_bonus_status(store, partner, product) -> Dict[str, Any]:
        """Получить статус бонуса для товара"""
        counter = StoreProductCounter.objects.filter(
            store=store,
            partner=partner,
            product=product
        ).first()

        if not counter:
            return {
                'total_count': 0,
                'product_count': 0,
                'next_bonus_at': 21,
                'bonus_available': False
            }

        return {
            'total_count': counter.total_count,
            'product_count': counter.product_count,
            'next_bonus_at': 21 - (counter.total_count % 21),
            'bonus_available': counter.check_bonus(),
            'last_bonus_at': counter.last_bonus_at
        }
