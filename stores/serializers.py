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


# =============================================================================
# ПАТЧ ДЛЯ stores/serializers.py - ДОБАВИТЬ В КОНЕЦ ФАЙЛА
# =============================================================================
#
# Новые сериализаторы для корзины магазина (basket).
# Существующие сериализаторы БЕЗ ИЗМЕНЕНИЙ.
#
# ДОБАВИТЬ:
# 1. BasketItemSerializer - товар в корзине
# 2. BasketTotalsSerializer - итоги корзины
# 3. BasketSerializer - полная корзина
# 4. BasketConfirmRequestSerializer - запрос на подтверждение
# 5. BasketConfirmResponseSerializer - ответ на подтверждение
# 6. ReportDefectRequestSerializer - запрос на отметку брака
# =============================================================================


# =============================================================================
# КОРЗИНА МАГАЗИНА (НОВОЕ v2.3)
# =============================================================================

class BasketItemSerializer(serializers.Serializer):
    """
    Сериализатор товара в корзине.

    Корзина = агрегированные товары из IN_TRANSIT заказов.
    """

    product_id = serializers.IntegerField(help_text='ID товара')
    product_name = serializers.CharField(help_text='Название товара')
    product_image = serializers.CharField(
        allow_null=True,
        help_text='URL изображения товара'
    )
    is_weight_based = serializers.BooleanField(help_text='Весовой товар')
    is_bonus_product = serializers.BooleanField(help_text='Бонусный товар')
    unit = serializers.CharField(help_text='Единица измерения')
    quantity = serializers.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text='Количество'
    )
    quantity_display = serializers.CharField(help_text='Отображение: "5 кг" или "100 шт"')
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Цена за единицу'
    )
    total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text='Сумма = количество × цена'
    )
    order_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text='ID заказов, содержащих этот товар'
    )


class BasketTotalsSerializer(serializers.Serializer):
    """Сериализатор итогов корзины."""

    piece_count = serializers.IntegerField(help_text='Общее количество штучных товаров')
    weight_total = serializers.CharField(help_text='Общий вес весовых товаров (кг)')
    total_amount = serializers.CharField(help_text='Общая сумма')


class BasketSerializer(serializers.Serializer):
    """
    Сериализатор корзины магазина.

    GET /api/stores/stores/{id}/basket/
    """

    store_id = serializers.IntegerField(help_text='ID магазина')
    store_name = serializers.CharField(help_text='Название магазина')
    owner_name = serializers.CharField(help_text='Владелец магазина')
    store_phone = serializers.CharField(help_text='Телефон магазина')
    is_empty = serializers.BooleanField(help_text='Корзина пуста')
    orders_count = serializers.IntegerField(help_text='Количество заказов в корзине')
    order_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text='ID заказов'
    )
    items = BasketItemSerializer(many=True, help_text='Товары в корзине')
    totals = BasketTotalsSerializer(help_text='Итоги')


class BasketConfirmRequestSerializer(serializers.Serializer):
    """
    Сериализатор запроса на подтверждение корзины.

    POST /api/stores/stores/{id}/basket/confirm/
    """

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
        help_text='ID товаров для полного удаления из корзины'
    )
    items_to_modify = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text='Изменение количества: [{"product_id": 1, "new_quantity": 10}]'
    )

    def validate_items_to_modify(self, value):
        """Валидация items_to_modify."""
        validated = []

        for i, item in enumerate(value):
            product_id = item.get('product_id')
            new_quantity = item.get('new_quantity')

            if not product_id:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: не указан product_id'
                )

            if new_quantity is None:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: не указан new_quantity'
                )

            try:
                new_quantity = Decimal(str(new_quantity))
            except (ValueError, TypeError):
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: некорректное значение new_quantity'
                )

            if new_quantity < 0:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: new_quantity не может быть отрицательным'
                )

            validated.append({
                'product_id': int(product_id),
                'new_quantity': new_quantity,
            })

        return validated


class ConfirmedOrderSerializer(serializers.Serializer):
    """Сериализатор подтверждённого заказа."""

    order_id = serializers.IntegerField()
    total_amount = serializers.FloatField()
    prepayment = serializers.FloatField()
    debt = serializers.FloatField()


class BasketConfirmTotalsSerializer(serializers.Serializer):
    """Итоги подтверждения корзины."""

    total_amount = serializers.FloatField()
    prepayment = serializers.FloatField()
    debt_created = serializers.FloatField()


class RemovedItemSerializer(serializers.Serializer):
    """Удалённый товар."""

    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    quantity = serializers.FloatField()
    order_id = serializers.IntegerField()


class ModifiedItemSerializer(serializers.Serializer):
    """Изменённый товар."""

    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    old_quantity = serializers.FloatField()
    new_quantity = serializers.FloatField()
    order_id = serializers.IntegerField()


# ============================================================================
# ПАТЧ ДЛЯ apps/stores/serializers.py - ДОБАВИТЬ НОВЫЕ СЕРИАЛИЗАТОРЫ
# ============================================================================
#
# ДОБАВИТЬ В КОНЕЦ ФАЙЛА (после строки 859)
# Эти сериализаторы для нового метода remove_from_basket
# ============================================================================

# =============================================================================
# УДАЛЕНИЕ/ИЗМЕНЕНИЕ ТОВАРОВ ИЗ КОРЗИНЫ (НОВОЕ v2.4)
# =============================================================================

class BasketRemoveRequestSerializer(serializers.Serializer):
    """
    Сериализатор запроса на удаление/изменение товаров из корзины.

    POST /api/stores/stores/{id}/basket/remove/

    ЛОГИКА:
    - items_to_remove: полностью удаляет товары по ID
    - items_to_modify: удаляет УКАЗАННОЕ количество (не уменьшает ДО)
    """

    items_to_remove = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        help_text='ID товаров для полного удаления из корзины'
    )
    items_to_modify = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text='Товары с количеством ДЛЯ УДАЛЕНИЯ (не финальное количество!)'
    )

    def validate(self, data):
        """Валидация: должно быть указано хотя бы что-то."""
        if not data.get('items_to_remove') and not data.get('items_to_modify'):
            raise serializers.ValidationError(
                'Укажите items_to_remove или items_to_modify'
            )
        return data

    def validate_items_to_modify(self, value):
        """
        Валидация items_to_modify.

        ВАЖНО: quantity_to_remove - это сколько УДАЛИТЬ, не финальное количество!
        """
        validated = []

        for i, item in enumerate(value):
            product_id = item.get('product_id')
            quantity_to_remove = item.get('quantity_to_remove')

            if not product_id:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: не указан product_id'
                )

            if quantity_to_remove is None:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: не указан quantity_to_remove'
                )

            try:
                quantity_to_remove = Decimal(str(quantity_to_remove))
            except (ValueError, TypeError):
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: некорректное значение quantity_to_remove'
                )

            if quantity_to_remove <= 0:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: quantity_to_remove должно быть больше 0'
                )

            validated.append({
                'product_id': int(product_id),
                'quantity_to_remove': quantity_to_remove,
            })

        return validated


class ModifiedItemInfoSerializer(serializers.Serializer):
    """Информация об изменённом товаре (частичное удаление)."""

    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    quantity_before = serializers.FloatField(help_text='Количество до удаления')
    quantity_removed = serializers.FloatField(help_text='Сколько удалили')
    quantity_after = serializers.FloatField(help_text='Количество после удаления')
    order_id = serializers.IntegerField()


class RemovedItemInfoSerializer(serializers.Serializer):
    """Информация об удалённом товаре (полное удаление)."""

    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    quantity_removed = serializers.FloatField(help_text='Сколько удалили')
    order_id = serializers.IntegerField()


class BasketRemoveResponseSerializer(serializers.Serializer):
    """
    Сериализатор ответа на удаление/изменение товаров из корзины.

    Возвращает обновлённую корзину + информацию об изменениях.
    """

    success = serializers.BooleanField()
    message = serializers.CharField()
    removed_items = RemovedItemInfoSerializer(many=True, help_text='Полностью удалённые товары')
    modified_items = ModifiedItemInfoSerializer(many=True, help_text='Частично удалённые товары')
    basket = BasketSerializer()


# =============================================================================
# ОБНОВЛЕННЫЙ СЕРИАЛИЗАТОР ДЛЯ CONFIRM (УПРОЩЕННЫЙ)
# =============================================================================

class BasketConfirmRequestUpdatedSerializer(serializers.Serializer):
    """
    Упрощенный сериализатор запроса на подтверждение корзины.

    POST /api/stores/stores/{id}/basket/confirm/

    ИЗМЕНЕНИЯ v2.4:
    - Удалены items_to_remove и items_to_modify
    - Остался только prepayment_amount
    """

    prepayment_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        min_value=Decimal('0'),
        help_text='Сумма предоплаты'
    )


class BasketConfirmResponseUpdatedSerializer(serializers.Serializer):
    """
    Упрощенный сериализатор ответа на подтверждение корзины.

    ИЗМЕНЕНИЯ v2.4:
    - Удалены removed_items и modified_items
    - Остались только подтвержденные заказы и итоги
    """

    success = serializers.BooleanField()
    message = serializers.CharField()
    confirmed_orders = ConfirmedOrderSerializer(many=True)
    totals = BasketConfirmTotalsSerializer()
    store_debt = serializers.FloatField()


# ============================================================================
# ИНСТРУКЦИИ ПО ОБНОВЛЕНИЮ
# ============================================================================
#
# ОПЦИОНАЛЬНО: Если хотите использовать обновленные сериализаторы
# (без items_to_remove/items_to_modify), замените старые:
#
# BasketConfirmRequestSerializer → BasketConfirmRequestUpdatedSerializer
# BasketConfirmResponseSerializer → BasketConfirmResponseUpdatedSerializer
#
# Или оставьте старые сериализаторы для обратной совместимости.
# ============================================================================


# =============================================================================
# ОТМЕТКА БРАКА (НОВОЕ v2.3)
# =============================================================================

class ReportDefectRequestSerializer(serializers.Serializer):
    """
    Сериализатор запроса на отметку брака.

    POST /api/stores/stores/{id}/inventory/report-defect/
    """

    product_id = serializers.IntegerField(help_text='ID товара из инвентаря')
    quantity = serializers.DecimalField(
        max_digits=10,
        decimal_places=3,
        min_value=Decimal('0.001'),
        help_text='Количество бракованного товара'
    )
    reason = serializers.CharField(
        max_length=500,
        help_text='Причина брака'
    )

    def validate_reason(self, value):
        """Валидация причины."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Причина брака обязательна')
        return value


class DefectInfoSerializer(serializers.Serializer):
    """Информация о созданном браке."""

    id = serializers.IntegerField()
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    quantity = serializers.FloatField()
    price = serializers.FloatField()
    total_amount = serializers.FloatField()
    reason = serializers.CharField()


class ReportDefectResponseSerializer(serializers.Serializer):
    """Сериализатор ответа на отметку брака."""

    success = serializers.BooleanField()
    message = serializers.CharField()
    defect = DefectInfoSerializer()
    store_debt = serializers.FloatField()