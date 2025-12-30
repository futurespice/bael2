# apps/orders/serializers.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.2
"""
Сериализаторы для orders согласно ТЗ v2.0 и дизайну.

ИЗМЕНЕНИЯ v2.2:
1. Добавлены поля owner_name, store_phone в список заказов
2. Добавлена сводка items_summary (Запрос на 900 шт 20кг)
3. Убраны лишние поля partner/partner_name из списков
4. Добавлен StoreOrderDetailForStoreSerializer для my-orders/{id}
5. Улучшено отображение товаров (quantity_display: "5 кг" или "545 шт")
"""

from decimal import Decimal
from typing import Dict, Any, List, Optional

from rest_framework import serializers

from products.models import Product
from .models import (
    StoreOrder,
    StoreOrderItem,
    StoreOrderStatus,
    DebtPayment,
    DefectiveProduct,
    OrderHistory,
)


# =============================================================================
# ITEM SERIALIZERS
# =============================================================================

class StoreOrderItemSerializer(serializers.ModelSerializer):
    """
    Сериализатор позиции заказа магазина.

    Используется для детального просмотра заказа.
    """

    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unit = serializers.CharField(source='product.unit', read_only=True)
    is_weight_based = serializers.BooleanField(
        source='product.is_weight_based',
        read_only=True
    )
    # Новое поле: отображение количества с единицей измерения
    quantity_display = serializers.SerializerMethodField(
        help_text='Количество с единицей измерения (5 кг или 545 шт)'
    )
    # Бонус в процентах (для отображения "0%" или "100%")
    bonus_percent = serializers.SerializerMethodField(
        help_text='Процент бонуса (0% или 100% если бонусный)'
    )

    class Meta:
        model = StoreOrderItem
        fields = [
            'id',
            'product',
            'product_name',
            'product_unit',
            'is_weight_based',
            'quantity',
            'quantity_display',
            'price',
            'total',
            'is_bonus',
            'bonus_percent',
        ]
        read_only_fields = ['id', 'total']

    def get_quantity_display(self, obj: StoreOrderItem) -> str:
        """
        Форматирование количества с единицей измерения.

        Примеры:
        - Весовой товар: "5 кг" или "2.5 кг"
        - Штучный товар: "545 шт"
        """
        if obj.product.is_weight_based:
            # Для весовых - показываем кг
            qty = obj.quantity
            if qty == int(qty):
                return f"{int(qty)} кг"
            return f"{qty} кг"
        else:
            # Для штучных - показываем шт
            qty = int(obj.quantity)
            return f"{qty} шт"

    def get_bonus_percent(self, obj: StoreOrderItem) -> str:
        """Процент бонуса для отображения."""
        return "100%" if obj.is_bonus else "0%"


# =============================================================================
# ADMIN TRACKER SERIALIZERS
# =============================================================================

class StoreOrderListSerializer(serializers.ModelSerializer):
    """
    Сериализатор списка заказов для АДМИНА (трекер).

    Соответствует дизайну "Запросы товаров":
    - Магазин: Эргешов Тынчтык (owner_name)
    - +996 999 888 777 (store_phone)
    - Статус: Принят / В ожидании / Отклонен / В пути
    - Запрос на 900 шт 20кг (items_summary)
    - №1, дата

    GET /api/orders/store-orders/
    """

    # Данные магазина
    store_name = serializers.CharField(
        source='store.name',
        read_only=True,
        help_text='Название магазина'
    )
    owner_name = serializers.CharField(
        source='store.owner_name',
        read_only=True,
        help_text='ФИО владельца магазина'
    )
    store_phone = serializers.CharField(
        source='store.phone',
        read_only=True,
        help_text='Номер телефона магазина'
    )

    # Статус
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
        help_text='Текстовое представление статуса'
    )

    # Сводка по товарам
    items_summary = serializers.SerializerMethodField(
        help_text='Сводка: "Запрос на 900 шт 20кг"'
    )
    piece_count = serializers.SerializerMethodField(
        help_text='Количество штучных товаров'
    )
    weight_total = serializers.SerializerMethodField(
        help_text='Общий вес весовых товаров (кг)'
    )
    items_count = serializers.SerializerMethodField(
        help_text='Общее количество позиций в заказе'
    )

    class Meta:
        model = StoreOrder
        fields = [
            'id',
            'store',
            'store_name',
            'owner_name',
            'store_phone',
            'status',
            'status_display',
            'total_amount',
            'items_summary',
            'piece_count',
            'weight_total',
            'items_count',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_items_summary(self, obj: StoreOrder) -> str:
        """
        Генерация сводки по товарам.

        Формат: "Запрос на 900 шт 20кг"
        """
        items = obj.items.select_related('product').all()

        piece_count = 0
        weight_total = Decimal('0')

        for item in items:
            if item.product.is_weight_based:
                weight_total += item.quantity
            else:
                piece_count += int(item.quantity)

        parts = []
        if piece_count > 0:
            parts.append(f"{piece_count} шт")
        if weight_total > 0:
            # Форматируем вес
            if weight_total == int(weight_total):
                parts.append(f"{int(weight_total)}кг")
            else:
                parts.append(f"{weight_total}кг")

        if parts:
            return f"Запрос на {' '.join(parts)}"
        return "Пустой запрос"

    def get_piece_count(self, obj: StoreOrder) -> int:
        """Количество штучных товаров."""
        items = obj.items.select_related('product').all()
        return sum(
            int(item.quantity)
            for item in items
            if not item.product.is_weight_based
        )

    def get_weight_total(self, obj: StoreOrder) -> str:
        """Общий вес весовых товаров."""
        items = obj.items.select_related('product').all()
        total = sum(
            item.quantity
            for item in items
            if item.product.is_weight_based
        )
        if total == int(total):
            return f"{int(total)}"
        return str(total)

    def get_items_count(self, obj: StoreOrder) -> int:
        """Общее количество позиций в заказе."""
        return obj.items.count()


class StoreOrderDetailSerializer(serializers.ModelSerializer):
    """
    Детальный сериализатор заказа для АДМИНА.

    Соответствует дизайну "Запрос":
    - Магазин: Сыдыков Тариэл Кнатбекович (owner_name)
    - Номер телефона: +996777999666
    - Товары с деталями (название, кол-во, цена, бонус)
    - Итого: Количество X, Сумма Y
    - Кнопки: Отклонить / Принять

    GET /api/orders/store-orders/{id}/
    """

    # Данные магазина
    store_name = serializers.CharField(
        source='store.name',
        read_only=True
    )
    store_inn = serializers.CharField(
        source='store.inn',
        read_only=True
    )
    owner_name = serializers.CharField(
        source='store.owner_name',
        read_only=True,
        help_text='ФИО владельца магазина'
    )
    store_phone = serializers.CharField(
        source='store.phone',
        read_only=True,
        help_text='Номер телефона магазина'
    )
    store_address = serializers.CharField(
        source='store.address',
        read_only=True,
        help_text='Адрес магазина'
    )

    # Статус
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    # Товары
    items = StoreOrderItemSerializer(many=True, read_only=True)

    # Сводка
    items_summary = serializers.SerializerMethodField()
    total_items_count = serializers.SerializerMethodField(
        help_text='Общее количество единиц товаров'
    )

    # Workflow поля (только для просмотра)
    reviewed_by_name = serializers.SerializerMethodField()

    # Финансовые поля показываем только после подтверждения
    outstanding_debt = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True
    )
    is_fully_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = StoreOrder
        fields = [
            'id',
            # Магазин
            'store',
            'store_name',
            'store_inn',
            'owner_name',
            'store_phone',
            'store_address',
            # Статус
            'status',
            'status_display',
            # Товары
            'items',
            'items_summary',
            'total_items_count',
            # Финансы
            'total_amount',
            'prepayment_amount',
            'debt_amount',
            'paid_amount',
            'outstanding_debt',
            'is_fully_paid',
            # Workflow
            'reviewed_by',
            'reviewed_by_name',
            'reviewed_at',
            'reject_reason',
            # Даты
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'status', 'debt_amount', 'paid_amount',
            'reviewed_by', 'reviewed_at',
            'created_at', 'updated_at'
        ]

    def get_items_summary(self, obj: StoreOrder) -> str:
        """Сводка по товарам."""
        items = obj.items.select_related('product').all()

        piece_count = 0
        weight_total = Decimal('0')

        for item in items:
            if item.product.is_weight_based:
                weight_total += item.quantity
            else:
                piece_count += int(item.quantity)

        parts = []
        if piece_count > 0:
            parts.append(f"{piece_count} шт")
        if weight_total > 0:
            if weight_total == int(weight_total):
                parts.append(f"{int(weight_total)} кг")
            else:
                parts.append(f"{weight_total} кг")

        return ' '.join(parts) if parts else "Пусто"

    def get_total_items_count(self, obj: StoreOrder) -> int:
        """Общее количество единиц товаров."""
        items = obj.items.select_related('product').all()
        total = 0
        for item in items:
            if item.product.is_weight_based:
                # Для весовых считаем как 1 позицию
                total += 1
            else:
                total += int(item.quantity)
        return total

    def get_reviewed_by_name(self, obj: StoreOrder) -> Optional[str]:
        """Имя админа, рассмотревшего заказ."""
        return obj.reviewed_by.get_full_name() if obj.reviewed_by else None


# =============================================================================
# STORE (МАГАЗИН) TRACKER SERIALIZERS
# =============================================================================

class StoreOrderForStoreListSerializer(serializers.ModelSerializer):
    """
    Сериализатор списка заказов для МАГАЗИНА (трекер my-orders).

    Соответствует дизайну "Запросы":
    - Эргешов Тынчтык (owner_name - свой магазин)
    - +996 999 888 777 (store_phone)
    - Статус: Принят / В ожидании / Отклонен / В пути / Доставлен
    - Запрос на 900 шт 20кг
    - №1, дата

    GET /api/orders/store-orders/my-orders/
    """

    # Данные магазина
    store_name = serializers.CharField(
        source='store.name',
        read_only=True
    )
    owner_name = serializers.CharField(
        source='store.owner_name',
        read_only=True,
        help_text='ФИО владельца магазина'
    )
    store_phone = serializers.CharField(
        source='store.phone',
        read_only=True,
        help_text='Номер телефона магазина'
    )

    # Статус
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    # Сводка по товарам
    items_summary = serializers.SerializerMethodField(
        help_text='Сводка: "Запрос на 900 шт 20кг"'
    )
    piece_count = serializers.SerializerMethodField()
    weight_total = serializers.SerializerMethodField()
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = StoreOrder
        fields = [
            'id',
            'store',
            'store_name',
            'owner_name',
            'store_phone',
            'status',
            'status_display',
            'total_amount',
            'items_summary',
            'piece_count',
            'weight_total',
            'items_count',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_items_summary(self, obj: StoreOrder) -> str:
        """Генерация сводки по товарам."""
        items = obj.items.select_related('product').all()

        piece_count = 0
        weight_total = Decimal('0')

        for item in items:
            if item.product.is_weight_based:
                weight_total += item.quantity
            else:
                piece_count += int(item.quantity)

        parts = []
        if piece_count > 0:
            parts.append(f"{piece_count} шт")
        if weight_total > 0:
            if weight_total == int(weight_total):
                parts.append(f"{int(weight_total)}кг")
            else:
                parts.append(f"{weight_total}кг")

        if parts:
            return f"Запрос на {' '.join(parts)}"
        return "Пустой запрос"

    def get_piece_count(self, obj: StoreOrder) -> int:
        """Количество штучных товаров."""
        return sum(
            int(item.quantity)
            for item in obj.items.select_related('product').all()
            if not item.product.is_weight_based
        )

    def get_weight_total(self, obj: StoreOrder) -> str:
        """Общий вес весовых товаров."""
        total = sum(
            item.quantity
            for item in obj.items.select_related('product').all()
            if item.product.is_weight_based
        )
        if total == int(total):
            return f"{int(total)}"
        return str(total)

    def get_items_count(self, obj: StoreOrder) -> int:
        """Общее количество позиций."""
        return obj.items.count()


class StoreOrderDetailForStoreSerializer(serializers.ModelSerializer):
    """
    Детальный сериализатор заказа для МАГАЗИНА.

    Соответствует дизайну детального просмотра заказа магазином.
    Показывает товары в формате каталога с "Запрошено: X шт/кг".

    GET /api/orders/store-orders/my-orders/{id}/
    """

    # Данные магазина
    store_name = serializers.CharField(source='store.name', read_only=True)
    owner_name = serializers.CharField(source='store.owner_name', read_only=True)
    store_phone = serializers.CharField(source='store.phone', read_only=True)

    # Статус
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    # Товары в формате каталога
    items = serializers.SerializerMethodField(
        help_text='Товары в формате каталога с "Запрошено"'
    )

    # Сводка
    items_summary = serializers.SerializerMethodField()
    total_items_count = serializers.SerializerMethodField()

    # Финансы (показываем только после принятия)
    outstanding_debt = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = StoreOrder
        fields = [
            'id',
            # Магазин
            'store',
            'store_name',
            'owner_name',
            'store_phone',
            # Статус
            'status',
            'status_display',
            # Товары
            'items',
            'items_summary',
            'total_items_count',
            # Финансы
            'total_amount',
            'prepayment_amount',
            'debt_amount',
            'paid_amount',
            'outstanding_debt',
            # Даты
            'created_at',
            'reviewed_at',
            'confirmed_at',
        ]
        read_only_fields = fields

    def get_items(self, obj: StoreOrder) -> List[Dict[str, Any]]:
        """
        Товары в формате каталога.

        По дизайну показывает:
        - Изображение товара
        - Название: "Курица"
        - Запрошено: "5 кг" или "545 шт"
        - Цена: "450,00 с"
        - Бонусный (звёздочка)
        """
        items = obj.items.select_related('product').all()
        result = []

        for item in items:
            product = item.product

            # Форматируем "Запрошено"
            if product.is_weight_based:
                qty = item.quantity
                if qty == int(qty):
                    requested = f"{int(qty)} кг"
                else:
                    requested = f"{qty} кг"
            else:
                requested = f"{int(item.quantity)} шт"

            # Получаем главное изображение
            main_image = None
            if hasattr(product, 'images'):
                first_image = product.images.first()
                if first_image and first_image.image:
                    main_image = first_image.image.url

            result.append({
                'id': item.id,
                'product_id': product.id,
                'product_name': product.name,
                'product_image': main_image,
                'is_weight_based': product.is_weight_based,
                'is_bonus_product': product.is_bonus,  # Товар бонусный (звёздочка)
                'requested': requested,  # "5 кг" или "545 шт"
                'quantity': str(item.quantity),
                'price': str(item.price),
                'total': str(item.total),
                'is_bonus_item': item.is_bonus,  # Эта позиция бонусная
            })

        return result

    def get_items_summary(self, obj: StoreOrder) -> str:
        """Сводка по товарам."""
        items = obj.items.select_related('product').all()

        piece_count = 0
        weight_total = Decimal('0')

        for item in items:
            if item.product.is_weight_based:
                weight_total += item.quantity
            else:
                piece_count += int(item.quantity)

        parts = []
        if piece_count > 0:
            parts.append(f"{piece_count} шт")
        if weight_total > 0:
            if weight_total == int(weight_total):
                parts.append(f"{int(weight_total)} кг")
            else:
                parts.append(f"{weight_total} кг")

        return ' '.join(parts) if parts else "Пусто"

    def get_total_items_count(self, obj: StoreOrder) -> int:
        """Общее количество единиц товаров."""
        items = obj.items.select_related('product').all()
        total = 0
        for item in items:
            if item.product.is_weight_based:
                total += 1
            else:
                total += int(item.quantity)
        return total


# =============================================================================
# CREATE/UPDATE SERIALIZERS (без изменений)
# =============================================================================

class StoreOrderCreateSerializer(serializers.Serializer):
    """Сериализатор создания заказа магазина."""

    items = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        help_text='Список товаров: [{"product_id": 1, "quantity": "10"}]'
    )
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64
    )

    def validate_items(self, value: List[Dict]) -> List[Dict]:
        """Валидация товаров."""
        validated = []

        for i, item in enumerate(value):
            # Проверка product_id
            product_id = item.get('product_id')
            if not product_id:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: не указан product_id'
                )

            # Проверка существования товара
            try:
                product = Product.objects.get(pk=product_id, is_active=True)
            except Product.DoesNotExist:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: товар с ID {product_id} не найден или неактивен'
                )

            # Проверка quantity
            quantity = item.get('quantity')
            if not quantity:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: не указано количество'
                )

            try:
                quantity = Decimal(str(quantity))
            except:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: некорректное количество "{quantity}"'
                )

            if quantity <= 0:
                raise serializers.ValidationError(
                    f'Позиция {i + 1}: количество должно быть больше 0'
                )

            # Валидация весовых товаров
            if product.is_weight_based:
                # Минимум 1 кг (или 0.1 кг если остаток < 1 кг)
                min_qty = Decimal('1') if product.stock_quantity >= 1 else Decimal('0.1')
                if quantity < min_qty:
                    raise serializers.ValidationError(
                        f'Позиция {i + 1}: минимальное количество для "{product.name}" - {min_qty} кг'
                    )

                # Шаг 0.1 кг
                if (quantity * 10) % 1 != 0:
                    raise serializers.ValidationError(
                        f'Позиция {i + 1}: количество для "{product.name}" должно быть кратно 0.1 кг'
                    )

            validated.append({
                'product_id': product_id,
                'quantity': quantity,
                'price': item.get('price'),
                'is_bonus': item.get('is_bonus', False),
            })

        return validated


class OrderApproveSerializer(serializers.Serializer):
    """Сериализатор одобрения заказа админом."""

    assign_to_partner_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='ID партнёра для назначения (опционально)'
    )


class OrderRejectSerializer(serializers.Serializer):
    """Сериализатор отклонения заказа админом."""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text='Причина отклонения'
    )


# =============================================================================
# DEBT & DEFECTIVE SERIALIZERS (без изменений)
# =============================================================================

class DebtPaymentSerializer(serializers.ModelSerializer):
    """Сериализатор погашения долга."""

    paid_by_name = serializers.SerializerMethodField()
    received_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DebtPayment
        fields = [
            'id',
            'order',
            'amount',
            'paid_by',
            'paid_by_name',
            'received_by',
            'received_by_name',
            'comment',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_paid_by_name(self, obj: DebtPayment) -> Optional[str]:
        return obj.paid_by.get_full_name() if obj.paid_by else None

    def get_received_by_name(self, obj: DebtPayment) -> Optional[str]:
        return obj.received_by.get_full_name() if obj.received_by else None


class PayDebtSerializer(serializers.Serializer):
    """Погашение долга."""

    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.01'),
        help_text='Сумма погашения'
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500
    )


class DefectiveProductSerializer(serializers.ModelSerializer):
    """Сериализатор бракованного товара."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    reported_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    class Meta:
        model = DefectiveProduct
        fields = [
            'id',
            'order',
            'product',
            'product_name',
            'quantity',
            'price',
            'total_amount',
            'reason',
            'status',
            'status_display',
            'reported_by',
            'reported_by_name',
            'reviewed_by',
            'reviewed_by_name',
            'created_at',
        ]
        read_only_fields = ['id', 'total_amount', 'created_at']

    def get_reported_by_name(self, obj: DefectiveProduct) -> Optional[str]:
        return obj.reported_by.get_full_name() if obj.reported_by else None

    def get_reviewed_by_name(self, obj: DefectiveProduct) -> Optional[str]:
        return obj.reviewed_by.get_full_name() if obj.reviewed_by else None


# =============================================================================
# ORDER HISTORY SERIALIZER
# =============================================================================

class OrderHistorySerializer(serializers.ModelSerializer):
    """Сериализатор истории заказа."""

    changed_by_name = serializers.SerializerMethodField()
    order_type_display = serializers.CharField(
        source='get_order_type_display',
        read_only=True
    )
    product_name = serializers.CharField(
        source='product.name',
        read_only=True,
        allow_null=True
    )

    class Meta:
        model = OrderHistory
        fields = [
            'id',
            'order_type',
            'order_type_display',
            'order_id',
            'product',
            'product_name',
            'old_status',
            'new_status',
            'changed_by',
            'changed_by_name',
            'comment',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_changed_by_name(self, obj: OrderHistory) -> Optional[str]:
        return obj.changed_by.get_full_name() if obj.changed_by else 'Система'


# =============================================================================
# LEGACY SERIALIZER (для обратной совместимости)
# =============================================================================

# Оставляем старый StoreOrderForStoreSerializer как алиас
StoreOrderForStoreSerializer = StoreOrderForStoreListSerializer