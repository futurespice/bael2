# apps/stores/serializers.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Сериализаторы для stores согласно ТЗ v2.0.

ОСНОВНЫЕ СЕРИАЛИЗАТОРЫ:
- RegionSerializer: Регионы
- CitySerializer: Города
- StoreSerializer: Магазин (полная информация)
- StoreListSerializer: Магазин (список)
- StoreCreateSerializer: Создание магазина
- StoreUpdateSerializer: Обновление профиля
- StoreSelectionSerializer: Выбор магазина
- StoreInventorySerializer: Инвентарь
"""

from decimal import Decimal
from typing import Dict, Any

from rest_framework import serializers

from .models import (
    Region,
    City,
    Store,
    StoreSelection,
    StoreInventory,
)


# =============================================================================
# ГЕОГРАФИЯ
# =============================================================================

class RegionSerializer(serializers.ModelSerializer):
    """Сериализатор региона."""

    cities_count = serializers.SerializerMethodField()
    stores_count = serializers.SerializerMethodField()

    class Meta:
        model = Region
        fields = [
            'id',
            'name',
            'cities_count',
            'stores_count',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_cities_count(self, obj: Region) -> int:
        """Количество городов в регионе."""
        return obj.get_cities_count()

    def get_stores_count(self, obj: Region) -> int:
        """Количество магазинов в регионе."""
        return obj.get_stores_count()


class CitySerializer(serializers.ModelSerializer):
    """Сериализатор города."""

    region_name = serializers.CharField(source='region.name', read_only=True)
    stores_count = serializers.SerializerMethodField()

    class Meta:
        model = City
        fields = [
            'id',
            'name',
            'region',
            'region_name',
            'stores_count',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'region_name', 'created_at', 'updated_at']

    def get_stores_count(self, obj: City) -> int:
        """Количество магазинов в городе."""
        return obj.get_stores_count()


# =============================================================================
# МАГАЗИН
# =============================================================================

class StoreListSerializer(serializers.ModelSerializer):
    """
    Сериализатор для списка магазинов (краткая информация).

    Используется в:
    - GET /api/stores/ (список магазинов)
    - Поиск магазинов
    """

    region_name = serializers.CharField(source='region.name', read_only=True)
    city_name = serializers.CharField(source='city.name', read_only=True)
    approval_status_display = serializers.CharField(
        source='get_approval_status_display',
        read_only=True
    )

    class Meta:
        model = Store
        fields = [
            'id',
            'name',
            'inn',
            'owner_name',
            'phone',
            'region',
            'region_name',
            'city',
            'city_name',
            'address',
            'debt',
            'approval_status',
            'approval_status_display',
            'is_active',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class StoreSerializer(serializers.ModelSerializer):
    """
    Сериализатор магазина (полная информация).

    Используется в:
    - GET /api/stores/{id}/ (детальная информация)
    - Профиль магазина
    """

    region_name = serializers.CharField(source='region.name', read_only=True)
    city_name = serializers.CharField(source='city.name', read_only=True)
    approval_status_display = serializers.CharField(
        source='get_approval_status_display',
        read_only=True
    )

    # Дополнительные вычисляемые поля
    can_interact = serializers.BooleanField(read_only=True)
    is_frozen = serializers.BooleanField(read_only=True)
    is_approved = serializers.BooleanField(read_only=True)
    has_debt = serializers.BooleanField(read_only=True)
    outstanding_debt = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True
    )

    # Статистика
    total_orders_count = serializers.SerializerMethodField()
    accepted_orders_count = serializers.SerializerMethodField()
    inventory_items_count = serializers.SerializerMethodField()
    users_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            'id',
            'name',
            'inn',
            'owner_name',
            'phone',
            'region',
            'region_name',
            'city',
            'city_name',
            'address',
            'latitude',
            'longitude',
            'debt',
            'total_paid',
            'outstanding_debt',
            'has_debt',
            'approval_status',
            'approval_status_display',
            'is_active',
            'is_frozen',
            'is_approved',
            'can_interact',
            'total_orders_count',
            'accepted_orders_count',
            'inventory_items_count',
            'users_count',
            'created_by',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'debt',
            'total_paid',
            'approval_status',
            'is_active',
            'created_by',
            'created_at',
            'updated_at'
        ]

    def get_total_orders_count(self, obj: Store) -> int:
        """Общее количество заказов."""
        return obj.get_total_orders_count()

    def get_accepted_orders_count(self, obj: Store) -> int:
        """Количество принятых заказов."""
        return obj.get_accepted_orders_count()

    def get_inventory_items_count(self, obj: Store) -> int:
        """Количество позиций в инвентаре."""
        return obj.get_inventory_items_count()

    def get_users_count(self, obj: Store) -> int:
        """Количество пользователей в магазине."""
        return obj.get_users_count()


class StoreCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для регистрации магазина (ТЗ v2.0, раздел 1.4).

    Используется в:
    - POST /api/stores/ (регистрация нового магазина)

    Поля:
    - Название магазина
    - Владелец магазина
    - Номер телефона магазина
    - ИНН (12-14 цифр)
    - Город
    - Область
    - Адрес магазина
    """

    class Meta:
        model = Store
        fields = [
            'name',
            'inn',
            'owner_name',
            'phone',
            'region',
            'city',
            'address',
            'latitude',
            'longitude'
        ]

    def validate_inn(self, value: str) -> str:
        """Валидация ИНН."""
        # Проверка: только цифры
        if not value.isdigit():
            raise serializers.ValidationError('ИНН должен содержать только цифры')

        # Проверка: длина 12-14
        if not (12 <= len(value) <= 14):
            raise serializers.ValidationError('ИНН должен содержать от 12 до 14 цифр')

        # Проверка: уникальность
        if Store.objects.filter(inn=value).exists():
            raise serializers.ValidationError(
                f'Магазин с ИНН {value} уже зарегистрирован'
            )

        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация связанности город-регион."""
        city = attrs.get('city')
        region = attrs.get('region')

        if city and region and city.region_id != region.id:
            raise serializers.ValidationError({
                'city': f'Город {city.name} не принадлежит региону {region.name}'
            })

        return attrs


class StoreUpdateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для обновления профиля магазина.

    Используется в:
    - PATCH /api/stores/{id}/ (обновление профиля)

    Все поля опциональны.
    """

    class Meta:
        model = Store
        fields = [
            'name',
            'owner_name',
            'phone',
            'region',
            'city',
            'address',
            'latitude',
            'longitude'
        ]

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация связанности город-регион."""
        city = attrs.get('city')
        region = attrs.get('region', self.instance.region if self.instance else None)

        if city and region and city.region_id != region.id:
            raise serializers.ValidationError({
                'city': f'Город {city.name} не принадлежит региону {region.name}'
            })

        return attrs


# =============================================================================
# ВЫБОР МАГАЗИНА
# =============================================================================

class StoreSelectionSerializer(serializers.ModelSerializer):
    """
    Сериализатор для выбора магазина пользователем.

    ТЗ v2.0: "Пользователь может выбрать магазин из списка"
    """

    store_name = serializers.CharField(source='store.name', read_only=True)
    store_inn = serializers.CharField(source='store.inn', read_only=True)
    store_address = serializers.CharField(source='store.address', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = StoreSelection
        fields = [
            'id',
            'user',
            'user_name',
            'store',
            'store_name',
            'store_inn',
            'store_address',
            'is_current',
            'selected_at',
            'deselected_at'
        ]
        read_only_fields = [
            'id',
            'user',
            'is_current',
            'selected_at',
            'deselected_at'
        ]


class StoreSelectionCreateSerializer(serializers.Serializer):
    """
    Сериализатор для создания выбора магазина.

    Используется в:
    - POST /api/stores/select/ (выбрать магазин)
    """

    store_id = serializers.IntegerField(min_value=1)

    def validate_store_id(self, value: int) -> int:
        """Валидация существования и доступности магазина."""
        try:
            store = Store.objects.get(pk=value)
        except Store.DoesNotExist:
            raise serializers.ValidationError(f'Магазин с ID {value} не найден')

        # Проверка: магазин одобрен
        if store.approval_status != Store.ApprovalStatus.APPROVED:
            raise serializers.ValidationError(
                f'Магазин "{store.name}" не одобрен. Выбор невозможен.'
            )

        # Проверка: магазин активен
        if not store.is_active:
            raise serializers.ValidationError(
                f'Магазин "{store.name}" заблокирован. Выбор невозможен.'
            )

        return value


# =============================================================================
# ИНВЕНТАРЬ МАГАЗИНА
# =============================================================================

class StoreInventorySerializer(serializers.ModelSerializer):
    """
    Сериализатор инвентаря магазина.

    ТЗ v2.0: "Все заказы складываются в один инвентарь магазина"
    """

    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unit = serializers.CharField(source='product.unit', read_only=True)
    product_price = serializers.DecimalField(
        source='product.final_price',
        max_digits=10,
        decimal_places=2,
        read_only=True
    )
    is_weight_based = serializers.BooleanField(
        source='product.is_weight_based',
        read_only=True
    )
    total_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = StoreInventory
        fields = [
            'id',
            'store',
            'product',
            'product_name',
            'product_unit',
            'product_price',
            'is_weight_based',
            'quantity',
            'total_price',
            'last_updated',
            'created_at'
        ]
        read_only_fields = [
            'id',
            'store',
            'product',
            'last_updated',
            'created_at'
        ]


class StoreInventoryListSerializer(serializers.ModelSerializer):
    """
    Сериализатор инвентаря (краткая версия для списков).
    """

    product_name = serializers.CharField(source='product.name', read_only=True)
    product_price = serializers.DecimalField(
        source='product.final_price',
        max_digits=10,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = StoreInventory
        fields = [
            'id',
            'product',
            'product_name',
            'product_price',
            'quantity',
            'total_price',
            'last_updated'
        ]
        read_only_fields = ['id', 'last_updated']


# =============================================================================
# ПОИСК И ФИЛЬТРАЦИЯ
# =============================================================================

class StoreSearchSerializer(serializers.Serializer):
    """
    Сериализатор для поиска и фильтрации магазинов (ТЗ v2.0).

    Поиск по:
    - ИНН (12-14 цифр)
    - Название
    - Город

    Фильтрация по:
    - Область
    - Город
    - Статус
    
    ИЗМЕНЕНИЕ v2.0 (требование #5):
    - Убраны фильтры по долгу: has_debt, min_debt, max_debt
    """

    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='Поиск по ИНН, названию, городу'
    )
    region_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text='ID региона'
    )
    city_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text='ID города'
    )
    is_active = serializers.BooleanField(
        required=False,
        help_text='Только активные / заблокированные'
    )
    approval_status = serializers.ChoiceField(
        choices=Store.ApprovalStatus.choices,
        required=False,
        help_text='Статус одобрения'
    )
    # ПРИМЕЧАНИЕ: Фильтры has_debt, min_debt, max_debt удалены по требованию #5


# =============================================================================
# АДМИНИСТРАТИВНЫЕ ДЕЙСТВИЯ
# =============================================================================

class StoreApproveSerializer(serializers.Serializer):
    """Сериализатор для одобрения магазина."""

    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text='Комментарий админа'
    )


class StoreRejectSerializer(serializers.Serializer):
    """Сериализатор для отклонения магазина."""

    reason = serializers.CharField(
        required=True,
        max_length=500,
        help_text='Причина отклонения'
    )


class StoreFreezeSerializer(serializers.Serializer):
    """
    Сериализатор для заморозки магазина.

    POST /api/stores/{id}/freeze/
    Body: {"reason": "Нарушение условий работы"}

    Поля:
    - reason: Причина заморозки (опционально, до 500 символов)

    Пример запроса:
        {
            "reason": "Долг превысил лимит"
        }
    """

    reason = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text='Причина заморозки магазина (опционально)',
        label='Причина'
    )

    def validate_reason(self, value):
        """Валидация причины заморозки."""
        if value and len(value.strip()) == 0:
            return ''  # Пустая строка вместо пробелов
        return value.strip() if value else ''


class StoreUnfreezeSerializer(serializers.Serializer):
    """
    Сериализатор для разморозки магазина.

    POST /api/stores/{id}/unfreeze/
    Body: {"comment": "Нарушение устранено"}

    Поля:
    - comment: Комментарий к разморозке (опционально, до 500 символов)

    Пример запроса:
        {
            "comment": "Долг погашен полностью"
        }
    """

    comment = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text='Комментарий к разморозке магазина (опционально)',
        label='Комментарий'
    )

    def validate_comment(self, value):
        """Валидация комментария."""
        if value and len(value.strip()) == 0:
            return ''  # Пустая строка вместо пробелов
        return value.strip() if value else ''