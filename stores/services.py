# apps/stores/services.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Сервисы для работы с магазинами согласно ТЗ v2.0.

ОСНОВНЫЕ СЕРВИСЫ:
- StoreService: CRUD магазинов, управление статусами
- StoreSelectionService: Выбор магазина пользователем
- StoreInventoryService: Управление инвентарём
- GeographyService: Управление регионами и городами (админ)

ТЗ v2.0 ТРЕБОВАНИЯ:
- Общая база магазинов для всех пользователей role='store'
- Один пользователь только в одном магазине одновременно
- Несколько пользователей могут быть в одном магазине
- Инвентарь обновляется при одобрении админом
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Dict, Any, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet, Q, Sum, Count
from django.utils import timezone

from .models import (
    Store,
    StoreSelection,
    StoreInventory,
    Region,
    City,
)

import logging
from django.db import transaction
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class StoreCreateData:
    """Данные для создания магазина."""
    name: str
    inn: str
    owner_name: str
    phone: str
    region_id: int
    city_id: int
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class StoreUpdateData:
    """Данные для обновления магазина."""
    name: Optional[str] = None
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    region_id: Optional[int] = None
    city_id: Optional[int] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class StoreSearchFilters:
    """
    Фильтры для поиска магазинов.
    
    ИЗМЕНЕНИЕ v2.0 (требование #5):
    - Убраны фильтры по долгу: has_debt, min_debt, max_debt
    """
    search_query: Optional[str] = None  # ИНН, название, город
    region_id: Optional[int] = None
    city_id: Optional[int] = None
    is_active: Optional[bool] = None
    approval_status: Optional[str] = None


# =============================================================================
# STORE SERVICE
# =============================================================================

class StoreService:
    """
    Сервис для работы с магазинами.

    Основные операции:
    - Регистрация магазина
    - Обновление профиля
    - Поиск и фильтрация
    - Управление статусами (одобрение/блокировка)
    """

    @classmethod
    @transaction.atomic
    def create_store(
            cls,
            *,
            data: StoreCreateData,
            created_by: Optional['User'] = None
    ) -> Store:
        """
        Регистрация нового магазина (ТЗ v2.0, раздел 1.4).

        Args:
            data: Данные магазина
            created_by: Пользователь, создавший магазин

        Returns:
            Store в статусе PENDING

        Raises:
            ValidationError: Если данные некорректны
        """
        # Проверка: ИНН уникален
        if Store.objects.filter(inn=data.inn).exists():
            raise ValidationError(f'Магазин с ИНН {data.inn} уже зарегистрирован')

        # Проверка: город принадлежит региону
        try:
            city = City.objects.select_related('region').get(pk=data.city_id)
        except City.DoesNotExist:
            raise ValidationError(f'Город с ID {data.city_id} не найден')

        if city.region_id != data.region_id:
            raise ValidationError(
                f'Город {city.name} не принадлежит выбранному региону'
            )

        # Создаём магазин
        # ✅ ИСПРАВЛЕНИЕ v2.0: Автоматическое одобрение магазина
        store = Store.objects.create(
            name=data.name,
            inn=data.inn,
            owner_name=data.owner_name,
            phone=data.phone,
            region_id=data.region_id,
            city_id=data.city_id,
            address=data.address,
            latitude=data.latitude,
            longitude=data.longitude,
            created_by=created_by,
            approval_status=Store.ApprovalStatus.APPROVED  # ✅ Было PENDING
        )

        return store

    @classmethod
    @transaction.atomic
    def update_store(
            cls,
            *,
            store: Store,
            data: StoreUpdateData,
            updated_by: Optional['User'] = None
    ) -> Store:
        """
        Обновление профиля магазина.

        Args:
            store: Магазин для обновления
            data: Новые данные
            updated_by: Кто обновил

        Returns:
            Обновлённый Store
        """
        # Обновляем только предоставленные поля
        if data.name is not None:
            store.name = data.name

        if data.owner_name is not None:
            store.owner_name = data.owner_name

        if data.phone is not None:
            store.phone = data.phone

        if data.address is not None:
            store.address = data.address

        if data.latitude is not None:
            store.latitude = data.latitude

        if data.longitude is not None:
            store.longitude = data.longitude

        # Обновление региона и города
        if data.region_id is not None or data.city_id is not None:
            region_id = data.region_id or store.region_id
            city_id = data.city_id or store.city_id

            city = City.objects.select_related('region').get(pk=city_id)

            if city.region_id != region_id:
                raise ValidationError('Город должен принадлежать выбранному региону')

            store.region_id = region_id
            store.city_id = city_id

        store.save()
        return store

    @classmethod
    def search_stores(cls, filters: StoreSearchFilters) -> QuerySet[Store]:
        """
        Поиск и фильтрация магазинов (ТЗ v2.0).

        Поиск по:
        - ИНН (12-14 цифр)
        - Название магазина
        - Город

        Фильтрация по:
        - Область
        - Город
        - Статус (активный/заблокированный)

        ИЗМЕНЕНИЕ v2.0 (требование #5):
        - Убраны фильтры по долгу

        Args:
            filters: Параметры поиска

        Returns:
            QuerySet магазинов
        """
        queryset = Store.objects.select_related('region', 'city')

        # Поиск по тексту
        if filters.search_query:
            query = filters.search_query.strip()
            queryset = queryset.filter(
                Q(inn__icontains=query) |
                Q(name__icontains=query) |
                Q(owner_name__icontains=query) |
                Q(city__name__icontains=query)
            )

        # Фильтр по региону
        if filters.region_id:
            queryset = queryset.filter(region_id=filters.region_id)

        # Фильтр по городу
        if filters.city_id:
            queryset = queryset.filter(city_id=filters.city_id)

        # Фильтр по статусу
        if filters.is_active is not None:
            queryset = queryset.filter(is_active=filters.is_active)

        if filters.approval_status:
            queryset = queryset.filter(approval_status=filters.approval_status)

        return queryset

    @classmethod
    def get_stores_by_debt_desc(cls) -> QuerySet[Store]:
        """
        Сортировка магазинов по долгу (от большего к меньшему).

        ТЗ: "Сортировка должников от большего к меньшему"

        Returns:
            QuerySet магазинов, отсортированных по долгу
        """
        return Store.objects.filter(
            debt__gt=Decimal('0')
        ).select_related('region', 'city').order_by('-debt')

    @classmethod
    @transaction.atomic
    def approve_store(cls, *, store: Store, approved_by: 'User') -> Store:
        """
        Одобрить магазин (только админ).

        Args:
            store: Магазин для одобрения
            approved_by: Админ

        Returns:
            Одобренный Store

        Raises:
            ValidationError: Если не админ или статус не PENDING
        """
        if approved_by.role != 'admin':
            raise ValidationError('Только администратор может одобрять магазины')

        if store.approval_status != Store.ApprovalStatus.PENDING:
            raise ValidationError(
                f'Можно одобрить только магазины в статусе "Ожидает одобрения". '
                f'Текущий статус: {store.get_approval_status_display()}'
            )

        store.approve(approved_by=approved_by)
        return store

    @classmethod
    @transaction.atomic
    def reject_store(
            cls,
            *,
            store: Store,
            rejected_by: 'User',
            reason: str = ''
    ) -> Store:
        """
        Отклонить магазин (только админ).

        Args:
            store: Магазин для отклонения
            rejected_by: Админ
            reason: Причина отклонения

        Returns:
            Отклонённый Store
        """
        if rejected_by.role != 'admin':
            raise ValidationError('Только администратор может отклонять магазины')

        store.reject(rejected_by=rejected_by, reason=reason)
        return store

    @classmethod
    @transaction.atomic
    def freeze_store(
            cls,
            *,
            store: 'Store',
            frozen_by: 'User',
            reason: str = ''
    ) -> 'Store':
        # Проверка прав доступа
        if frozen_by.role != 'admin':
            raise ValidationError(
                "Только администратор может замораживать магазины. "
                f"Ваша роль: {frozen_by.get_role_display()}"
            )

        # Проверка текущего статуса
        if not store.is_active:
            raise ValidationError(
                f"Магазин '{store.name}' уже заморожен и не может быть заморожен повторно."
            )

        # Замораживаем магазин
        store.is_active = False
        store.save(update_fields=['is_active'])

        # Логирование для аудита
        logger.warning(
            f"🔒 МАГАЗИН ЗАМОРОЖЕН | "
            f"ID={store.id} | "
            f"Название='{store.name}' | "
            f"Администратор={frozen_by.get_full_name()} (ID={frozen_by.id}) | "
            f"Причина: {reason or 'Не указана'}"
        )

        return store

    @classmethod
    @transaction.atomic
    def unfreeze_store(
            cls,
            *,
            store: 'Store',
            unfrozen_by: 'User',
            comment: str = ''
    ) -> 'Store':
        if unfrozen_by.role != 'admin':
            raise ValidationError(
                "Только администратор может размораживать магазины. "
                f"Ваша роль: {unfrozen_by.get_role_display()}"
            )

        # Проверка текущего статуса
        if store.is_active:
            raise ValidationError(
                f"Магазин '{store.name}' уже активен и не требует разморозки."
            )

        # Размораживаем магазин
        store.is_active = True
        store.save(update_fields=['is_active'])

        # Логирование для аудита
        logger.info(
            f"🔓 МАГАЗИН РАЗМОРОЖЕН | "
            f"ID={store.id} | "
            f"Название='{store.name}' | "
            f"Администратор={unfrozen_by.get_full_name()} (ID={unfrozen_by.id}) | "
            f"Комментарий: {comment or 'Не указан'}"
        )
        return store



# =============================================================================
# STORE SELECTION SERVICE
# =============================================================================

class StoreSelectionService:
    """
    Сервис для выбора магазина пользователем.

    ТЗ v2.0 ЛОГИКА:
    - Один пользователь может быть только в ОДНОМ магазине одновременно
    - Несколько пользователей могут быть в ОДНОМ магазине
    - При выборе нового магазина старый автоматически отменяется
    """

    @classmethod
    def get_current_store(cls, user: 'User') -> Optional[Store]:
        """
        Получить текущий активный магазин пользователя.

        Args:
            user: Пользователь с role='store'

        Returns:
            Store или None
        """
        return StoreSelection.get_current_store_for_user(user)

    @classmethod
    @transaction.atomic
    def select_store(cls, *, user: 'User', store_id: int) -> StoreSelection:
        """
        Выбрать магазин для работы.

        ТЗ: "Пользователь может выбрать магазин из списка.
        Один пользователь может быть только в одном магазине одновременно."

        Args:
            user: Пользователь
            store_id: ID магазина

        Returns:
            StoreSelection

        Raises:
            ValidationError: Если выбор невозможен
        """
        # Проверка роли
        if user.role != 'store':
            raise ValidationError(
                'Только пользователи с ролью "Магазин" могут выбирать магазины'
            )

        # Получаем магазин
        try:
            store = Store.objects.get(pk=store_id)
        except Store.DoesNotExist:
            raise ValidationError(f'Магазин с ID {store_id} не найден')

        # Проверка доступности магазина
        store.check_can_interact()

        # Создаём/обновляем выбор
        selection = StoreSelection.select_store(user=user, store=store)

        return selection

    @classmethod
    @transaction.atomic
    def deselect_store(cls, user: 'User') -> bool:
        """
        Отменить выбор текущего магазина.

        Args:
            user: Пользователь

        Returns:
            True если выбор был отменён
        """
        return StoreSelection.deselect_current_store(user)

    @classmethod
    def get_available_stores(cls, user: 'User') -> QuerySet[Store]:
        """
        Получить список доступных магазинов для выбора.

        ТЗ: "Общая база магазинов для всех пользователей role='store'"

        Args:
            user: Пользователь

        Returns:
            QuerySet магазинов (одобренные и активные)
        """
        return Store.objects.filter(
            approval_status=Store.ApprovalStatus.APPROVED,
            is_active=True
        ).select_related('region', 'city').order_by('name')

    @classmethod
    def get_users_in_store(cls, store: Store) -> QuerySet['User']:
        """
        Получить список пользователей, работающих в магазине.

        ТЗ: "Несколько пользователей могут быть в одном магазине одновременно"

        Args:
            store: Магазин

        Returns:
            QuerySet пользователей
        """
        from users.models import User

        user_ids = StoreSelection.objects.filter(
            store=store,
            is_current=True
        ).values_list('user_id', flat=True)

        return User.objects.filter(id__in=user_ids)


# =============================================================================
# STORE INVENTORY SERVICE
# =============================================================================

class StoreInventoryService:
    """
    Сервис для управления инвентарём магазина.

    ТЗ v2.0 ЛОГИКА:
    - Товары добавляются при одобрении заказа админом
    - Все заказы складываются в один инвентарь
    - Партнёр может удалить товары при подтверждении
    """

    @classmethod
    @transaction.atomic
    def add_to_inventory(
            cls,
            *,
            store: Store,
            product: 'Product',
            quantity: Decimal
    ) -> StoreInventory:
        """
        Добавить товар в инвентарь магазина.

        Используется при одобрении заказа админом.

        Args:
            store: Магазин
            product: Товар
            quantity: Количество

        Returns:
            StoreInventory
        """
        if quantity <= Decimal('0'):
            raise ValidationError('Количество должно быть больше 0')

        # Получаем или создаём запись в инвентаре
        inventory, created = StoreInventory.objects.get_or_create(
            store=store,
            product=product,
            defaults={'quantity': Decimal('0')}
        )

        # Добавляем количество
        inventory.add_quantity(quantity)

        return inventory

    @classmethod
    @transaction.atomic
    def remove_from_inventory(
            cls,
            *,
            store: Store,
            product: 'Product',
            quantity: Decimal
    ) -> Optional[StoreInventory]:
        """
        Удалить товар из инвентаря магазина.

        Используется партнёром при подтверждении заказа.

        Args:
            store: Магазин
            product: Товар
            quantity: Количество

        Returns:
            StoreInventory или None (если удалена полностью)
        """
        try:
            inventory = StoreInventory.objects.get(store=store, product=product)
        except StoreInventory.DoesNotExist:
            raise ValidationError(
                f'Товар {product.name} не найден в инвентаре магазина {store.name}'
            )

        # Вычитаем количество (автоматически удаляется если 0)
        inventory.subtract_quantity(quantity)

        # Проверяем, существует ли ещё запись
        if StoreInventory.objects.filter(pk=inventory.pk).exists():
            return inventory

        return None

    @classmethod
    def get_inventory(cls, store: Store) -> QuerySet[StoreInventory]:
        """
        Получить весь инвентарь магазина.

        Args:
            store: Магазин

        Returns:
            QuerySet инвентаря
        """
        return StoreInventory.objects.filter(
            store=store
        ).select_related('product').order_by('-last_updated')

    @classmethod
    def get_inventory_total_value(cls, store: Store) -> Decimal:
        """
        Общая стоимость инвентаря магазина.

        Args:
            store: Магазин

        Returns:
            Сумма всех товаров в инвентаре
        """
        inventory = cls.get_inventory(store)

        total = Decimal('0')
        for item in inventory:
            total += item.total_price

        return total


# =============================================================================
# BONUS CALCULATION SERVICE (НОВОЕ v2.0)
# =============================================================================

class BonusCalculationService:
    """
    Сервис для расчёта бонусов в инвентаре магазина (ТЗ v2.0).

    ЛОГИКА БОНУСОВ:
    - Каждый 21-й товар бесплатно (20 платных + 1 бонусный)
    - Бонусы применяются ТОЛЬКО к штучным товарам с флагом is_bonus=True
    - Весовые товары НЕ могут быть бонусными
    - Бонусы считаются по НАКОПЛЕННОМУ количеству в инвентаре

    ПРИМЕР:
    - Товар "Мороженое" (is_bonus=True)
    - Заказ #1: 15 шт → Инвентарь: 15
    - Заказ #2: 10 шт → Инвентарь: 25
    - Бонусы = 25 // 21 = 1 бонусный
    - Платных = 25 - 1 = 24 шт
    """

    BONUS_THRESHOLD = 21  # Каждый 21-й товар бесплатно

    @classmethod
    def calculate_bonuses_for_product(
            cls,
            total_quantity: int
    ) -> Dict[str, int]:
        """
        Рассчитать бонусы для товара по количеству.

        Args:
            total_quantity: Общее количество в инвентаре

        Returns:
            {
                'total': 25,
                'bonus_count': 1,
                'paid_count': 24
            }
        """
        bonus_count = total_quantity // cls.BONUS_THRESHOLD
        paid_count = total_quantity - bonus_count

        return {
            'total': total_quantity,
            'bonus_count': bonus_count,
            'paid_count': paid_count
        }

    @classmethod
    def get_inventory_with_bonuses(
            cls,
            store: Store
    ) -> List[Dict[str, Any]]:
        """
        Получить инвентарь магазина с расчётом бонусов.

        Args:
            store: Магазин

        Returns:
            List[Dict] с информацией о товарах и бонусах
        """
        inventory = StoreInventory.objects.filter(
            store=store
        ).select_related('product').order_by('-last_updated')

        result = []

        for item in inventory:
            product = item.product
            quantity = int(item.quantity)  # Для бонусов только целые

            item_data = {
                'id': item.id,
                'product_id': product.id,
                'product_name': product.name,
                'quantity': float(item.quantity),
                'unit_price': float(product.final_price),
                'is_weight_based': product.is_weight_based,
                'is_bonus_product': product.is_bonus,  # Флаг "бонусный товар"
                'bonus_count': 0,
                'paid_count': quantity,
                'total_price': float(item.total_price),
                'paid_price': float(item.total_price),
            }

            # Бонусы только для штучных товаров с is_bonus=True
            if product.is_bonus and not product.is_weight_based:
                bonus_info = cls.calculate_bonuses_for_product(quantity)
                item_data['bonus_count'] = bonus_info['bonus_count']
                item_data['paid_count'] = bonus_info['paid_count']
                # Платная сумма = paid_count × цена
                item_data['paid_price'] = float(
                    Decimal(str(bonus_info['paid_count'])) * product.final_price
                )

            result.append(item_data)

        return result

    @classmethod
    def get_total_bonuses_summary(
            cls,
            store: Store
    ) -> Dict[str, Any]:
        """
        Сводка по бонусам в инвентаре магазина.

        Args:
            store: Магазин

        Returns:
            {
                'total_bonus_items': 3,
                'total_bonus_value': 300.00,
                'products_with_bonuses': [...]
            }
        """
        inventory_with_bonuses = cls.get_inventory_with_bonuses(store)

        total_bonus_items = 0
        total_bonus_value = Decimal('0')
        products_with_bonuses = []

        for item in inventory_with_bonuses:
            if item['bonus_count'] > 0:
                total_bonus_items += item['bonus_count']
                bonus_value = Decimal(str(item['bonus_count'])) * Decimal(str(item['unit_price']))
                total_bonus_value += bonus_value

                products_with_bonuses.append({
                    'product_name': item['product_name'],
                    'total_quantity': item['quantity'],
                    'bonus_count': item['bonus_count'],
                    'paid_count': item['paid_count'],
                    'bonus_value': float(bonus_value)
                })

        return {
            'total_bonus_items': total_bonus_items,
            'total_bonus_value': float(total_bonus_value),
            'products_with_bonuses': products_with_bonuses
        }


# =============================================================================
# GEOGRAPHY SERVICE
# =============================================================================

class GeographyService:
    """
    Сервис для управления регионами и городами (только админ).

    ТЗ v2.0: "Области и города управляются админом"
    """

    @classmethod
    @transaction.atomic
    def create_region(cls, *, name: str, created_by: 'User') -> Region:
        """Создать регион (только админ)."""
        if created_by.role != 'admin':
            raise ValidationError('Только администратор может создавать регионы')

        if Region.objects.filter(name=name).exists():
            raise ValidationError(f'Регион "{name}" уже существует')

        return Region.objects.create(name=name)

    @classmethod
    @transaction.atomic
    def create_city(
            cls,
            *,
            region_id: int,
            name: str,
            created_by: 'User'
    ) -> City:
        """Создать город (только админ)."""
        if created_by.role != 'admin':
            raise ValidationError('Только администратор может создавать города')

        try:
            region = Region.objects.get(pk=region_id)
        except Region.DoesNotExist:
            raise ValidationError(f'Регион с ID {region_id} не найден')

        if City.objects.filter(region=region, name=name).exists():
            raise ValidationError(f'Город "{name}" уже существует в регионе {region.name}')

        return City.objects.create(region=region, name=name)

    @classmethod
    def get_all_regions(cls) -> QuerySet[Region]:
        """Получить все регионы."""
        return Region.objects.all().order_by('name')

    @classmethod
    def get_cities_by_region(cls, region_id: int) -> QuerySet[City]:
        """Получить города региона."""
        return City.objects.filter(region_id=region_id).order_by('name')