# apps/orders/models.py - ОЧИЩЕННАЯ ВЕРСИЯ v2.1
"""
Модели заказов согласно ТЗ v2.0.

ИЗМЕНЕНИЯ v2.1:
1. УДАЛЕНЫ PartnerOrder и PartnerOrderItem (по ТЗ v2.0)
2. УДАЛЁН PartnerOrderStatus

МОДЕЛИ:
- StoreOrder: Заказ магазина (основной workflow)
- StoreOrderItem: Позиция заказа магазина
- DebtPayment: Погашение долга
- DefectiveProduct: Бракованные товары
- OrderHistory: История изменений заказов

WORKFLOW (ТЗ v2.0):
1. Магазин создаёт заказ → status=PENDING
2. Админ одобряет → status=IN_TRANSIT, товары → инвентарь
3. Партнёр подтверждает через stores/.../inventory/confirm/ → status=ACCEPTED, долг
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, List

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from stores.models import Store


# =============================================================================
# PARTNER REQUEST (v3.0)
# =============================================================================

class PartnerRequestType(models.TextChoices):
    REQUEST = 'request', 'Запрос товара'
    RETURN = 'return', 'Возврат товара'


class PartnerRequestStatus(models.TextChoices):
    PENDING = 'pending', 'Ожидает'
    APPROVED = 'approved', 'Одобрено'
    REJECTED = 'rejected', 'Отклонено'


class PartnerRequest(models.Model):
    """
    Запросы партнера на товары (v3.0).
    
    ИЗМЕНЕНИЯ v3.0:
    - Поддержка НЕСКОЛЬКИХ товаров через PartnerRequestItem
    - Поля product/quantity оставлены для обратной совместимости
    - Добавлено поле notes
    
    WORKFLOW:
    1. Партнёр создаёт запрос с items[]
    2. Админ одобряет/отклоняет
    3. При одобрении товары → PartnerInventory
    """

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'partner'},
        related_name='product_requests'
    )

    # Оставлено для обратной совместимости (для запросов с одним товаром)
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='partner_requests',
        null=True,
        blank=True,
        help_text='Для обратной совместимости. Используйте items для v3.0'
    )

    request_type = models.CharField(
        max_length=10,
        choices=PartnerRequestType.choices
    )

    status = models.CharField(
        max_length=10,
        choices=PartnerRequestStatus.choices,
        default=PartnerRequestStatus.PENDING,
        db_index=True
    )

    # Оставлено для обратной совместимости
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        null=True,
        blank=True,
        help_text='Для обратной совместимости. Используйте items для v3.0'
    )

    reason = models.TextField(blank=True)
    
    # v3.0: Примечания к запросу
    notes = models.TextField(
        blank=True,
        verbose_name='Примечания',
        help_text='Дополнительные примечания к запросу'
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_partner_requests'
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'partner_requests'
        ordering = ['-created_at']
        verbose_name = 'Запрос партнёра'
        verbose_name_plural = 'Запросы партнёров'
        indexes = [
            models.Index(fields=['partner', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        items_count = self.items.count() if hasattr(self, 'items') else 0
        if items_count > 0:
            return f"{self.get_request_type_display()}: {items_count} товаров - {self.get_status_display()}"
        elif self.product:
            return f"{self.get_request_type_display()}: {self.product.name} - {self.get_status_display()}"
        return f"{self.get_request_type_display()} - {self.get_status_display()}"

    @property
    def is_pending(self):
        return self.status == PartnerRequestStatus.PENDING
    
    @property
    def total_amount(self) -> Decimal:
        """Общая сумма запроса."""
        if hasattr(self, 'items') and self.items.exists():
            return sum(
                item.total_amount  # ✅ Используем item.total_amount для единой логики
                for item in self.items.all()
            )
        elif self.product and self.quantity:
            return self.quantity * self.product.final_price
        return Decimal('0')
    
    @property
    def items_count(self) -> int:
        """Количество товаров в запросе."""
        if hasattr(self, 'items'):
            return self.items.count()
        return 1 if self.product else 0


class PartnerRequestItem(models.Model):
    """
    Позиция в запросе партнёра (v3.0).
    
    Позволяет добавлять несколько товаров в один запрос.
    
    Поддерживает:
    - Штучные товары: quantity
    - Весовые товары: quantity + weight
    """

    request = models.ForeignKey(
        PartnerRequest,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Запрос'
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='partner_request_items',
        verbose_name='Товар'
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество',
        help_text='Для штучных: количество шт. Для весовых: обычно 1'
    )

    weight = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.1'))],
        verbose_name='Вес (кг)',
        help_text='Только для весовых товаров, шаг 0.1 кг'
    )

    price_at_request = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена на момент запроса',
        help_text='За 1 шт или за 1 кг для весовых'
    )

    is_bonus = models.BooleanField(
        default=False,
        verbose_name='Бонусный запрос',
        help_text='Запрос на получение бонусного товара'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'partner_request_items'
        verbose_name = 'Позиция запроса партнёра'
        verbose_name_plural = 'Позиции запросов партнёров'
        unique_together = [['request', 'product', 'is_bonus']]
        indexes = [
            models.Index(fields=['request', 'product']),
            models.Index(fields=['is_bonus']),
        ]

    def __str__(self):
        bonus_mark = " [БОНУС]" if self.is_bonus else ""
        if self.weight:
            return f"{self.product.name}{bonus_mark}: {self.weight} кг"
        return f"{self.product.name}{bonus_mark}: {self.quantity} шт"

    @property
    def total_amount(self) -> Decimal:
        """Общая сумма позиции."""
        if self.is_bonus:
            return Decimal('0')
            
        if self.product.is_weight_based and self.weight:
            # Весовой: цена за 100г × кол-во 100г
            price_per_100g = self.price_at_request / Decimal('10')
            units_100g = self.weight / Decimal('0.1')
            return price_per_100g * units_100g
        else:
            # Штучный
            return self.quantity * self.price_at_request

    def save(self, *args, **kwargs):
        """Автоматическое заполнение цены."""
        if not self.price_at_request and self.product:
            self.price_at_request = self.product.final_price
        super().save(*args, **kwargs)

    def clean(self):
        """Валидация данных."""
        from django.core.exceptions import ValidationError

        if self.product and self.product.is_weight_based:
            if not self.weight:
                raise ValidationError({
                    'weight': 'Для весовых товаров обязательно указать вес'
                })
            if self.weight % Decimal('0.1') != 0:
                raise ValidationError({
                    'weight': 'Вес должен быть кратен 0.1 кг'
                })
        elif self.weight:
            raise ValidationError({
                'weight': 'Штучные товары не имеют веса'
            })


# =============================================================================
# ТИПЫ ЗАКАЗОВ (v3.0)
# =============================================================================

class StoreOrderType(models.TextChoices):
    """Типы заказов v3.0."""
    PREORDER = 'preorder', 'Предзаказ'
    MANUAL = 'manual', 'Ручной сбор'


# =============================================================================
# СТАТУСЫ ЗАКАЗОВ
# =============================================================================

class StoreOrderStatus(models.TextChoices):
    """
    Статусы заказа магазина согласно ТЗ v2.0.

    WORKFLOW:
    1. PENDING: Магазин создал заказ → ждёт админа
    2. IN_TRANSIT: Админ одобрил → товары в инвентарь → ждёт партнёра
    3. ACCEPTED: Партнёр подтвердил → создан долг
    4. REJECTED: Админ отклонил
    """
    PENDING = 'pending', _('В ожидании')
    IN_TRANSIT = 'in_transit', _('В пути')
    ACCEPTED = 'accepted', _('Принят')
    REJECTED = 'rejected', _('Отказано')


class OrderType(models.TextChoices):
    """Типы заказов для истории."""
    STORE = 'store', _('Заказ магазина')


# =============================================================================
# ПОГАШЕНИЕ ДОЛГОВ
# =============================================================================

class DebtPayment(models.Model):
    """
    Погашение долга по заказу магазина.

    Создаётся через:
    - POST /api/stores/{id}/pay-debt/

    Может быть частичным или полным.
    """

    order = models.ForeignKey(
        'StoreOrder',
        on_delete=models.CASCADE,
        related_name='debt_payments',
        verbose_name='Заказ'
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name='Сумма оплаты',
        help_text='Сумма погашения долга'
    )

    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='debt_payments_made',
        verbose_name='Кто оплатил'
    )

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='debt_payments_received',
        verbose_name='Кто принял оплату'
    )

    comment = models.TextField(
        blank=True,
        verbose_name='Комментарий'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата оплаты'
    )

    class Meta:
        db_table = 'debt_payments'
        ordering = ['-created_at']
        verbose_name = 'Погашение долга'
        verbose_name_plural = 'Погашения долгов'
        indexes = [
            models.Index(fields=['order', '-created_at']),
        ]

    def __str__(self) -> str:
        return f"Оплата {self.amount} сом по заказу #{self.order.id}"

    def clean(self) -> None:
        """Валидация суммы."""
        if self.amount <= Decimal('0'):
            raise ValidationError({'amount': 'Сумма должна быть больше 0'})


# =============================================================================
# ЗАКАЗЫ МАГАЗИНОВ (ОСНОВНОЙ WORKFLOW v2.0)
# =============================================================================

class StoreOrder(models.Model):
    """
    Заказ магазина согласно ТЗ v2.0.

    WORKFLOW:
    1. Магазин создаёт заказ → status=PENDING, partner=NULL
    2. Админ одобряет → status=IN_TRANSIT, товары → инвентарь магазина
    3. Партнёр подтверждает через stores/.../inventory/confirm/ → status=ACCEPTED, долг

    ВАЖНО:
    - partner может быть NULL при создании
    - prepayment_amount указывает партнёр при подтверждении
    - debt_amount = total_amount - prepayment_amount
    """

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name='Магазин'
    )

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role': 'partner'},
        related_name='store_orders',
        verbose_name='Партнёр',
        help_text='Назначается админом или автоматически'
    )

    status = models.CharField(
        max_length=16,
        choices=StoreOrderStatus.choices,
        default=StoreOrderStatus.PENDING,
        verbose_name='Статус'
    )

    # Тип заказа (v3.0)
    order_type = models.CharField(
        max_length=10,
        choices=StoreOrderType.choices,
        default=StoreOrderType.PREORDER,
        verbose_name='Тип заказа',
        help_text='Предзаказ или ручной сбор партнёром'
    )

    # Суммы
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Сумма заказа'
    )

    prepayment_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Предоплата',
        help_text='Указывается партнёром при подтверждении'
    )

    debt_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Долг',
        help_text='total_amount - prepayment_amount'
    )

    paid_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Оплачено'
    )

    # Workflow
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_store_orders',
        verbose_name='Создал'
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_store_orders',
        verbose_name='Рассмотрел (админ)'
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата рассмотрения'
    )

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_store_orders',
        verbose_name='Подтвердил (партнёр)'
    )

    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата подтверждения'
    )

    reject_reason = models.TextField(
        blank=True,
        verbose_name='Причина отказа'
    )

    notes = models.TextField(
        blank=True,
        verbose_name='Примечания к заказу',
        help_text='Дополнительные примечания (используется в ручных заказах)'
    )

    # Idempotency
    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        verbose_name='Ключ идемпотентности'
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )

    class Meta:
        db_table = 'store_orders'
        ordering = ['-created_at']
        verbose_name = 'Заказ магазина'
        verbose_name_plural = 'Заказы магазинов'
        indexes = [
            models.Index(fields=['store', '-created_at']),
            models.Index(fields=['partner', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['reviewed_by']),
            models.Index(fields=['confirmed_by']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self) -> str:
        return f"Заказ #{self.id} - {self.store.name} ({self.get_status_display()})"

    @property
    def outstanding_debt(self) -> Decimal:
        """Непогашенный долг."""
        return max(self.debt_amount - self.paid_amount, Decimal('0'))

    def calculate_total(self, save: bool = True) -> Decimal:
        """Пересчитать сумму заказа."""
        total = self.items.aggregate(
            s=models.Sum('total')
        ).get('s') or Decimal('0')

        self.total_amount = total

        if save:
            self.save(update_fields=['total_amount'])

        return total

    @transaction.atomic
    def pay_debt(
            self,
            amount: Decimal,
            paid_by: Optional['User'] = None,
            received_by: Optional['User'] = None,
            comment: str = ''
    ) -> DebtPayment:
        """
        Погасить долг по заказу.

        ВНИМАНИЕ: Рекомендуется использовать /api/stores/{id}/pay-debt/
        для погашения общего долга магазина.
        """
        if amount > self.outstanding_debt:
            raise ValidationError(
                f'Сумма ({amount}) превышает непогашенный долг ({self.outstanding_debt})'
            )

        payment = DebtPayment.objects.create(
            order=self,
            amount=amount,
            paid_by=paid_by,
            received_by=received_by,
            comment=comment
        )

        # Обновляем paid_amount
        StoreOrder.objects.filter(pk=self.pk).update(
            paid_amount=models.F('paid_amount') + amount
        )
        self.refresh_from_db()

        return payment


class StoreOrderItem(models.Model):
    """
    Позиция в заказе магазина.

    Содержит товар, количество, цену и признак бонуса.
    """

    order = models.ForeignKey(
        StoreOrder,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Заказ'
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='store_order_items',
        verbose_name='Товар'
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество'
    )

    # v3.0: Вес для весовых товаров
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.1'))],
        verbose_name='Вес (кг)',
        help_text='Только для весовых товаров, шаг 0.1 кг'
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена за единицу'
    )

    total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Сумма'
    )

    is_bonus = models.BooleanField(
        default=False,
        verbose_name='Бонусная позиция',
        help_text='Бесплатный товар (каждый 21-й)'
    )

    class Meta:
        db_table = 'store_order_items'
        verbose_name = 'Позиция заказа магазина'
        verbose_name_plural = 'Позиции заказов магазинов'

    def __str__(self) -> str:
        bonus_mark = " [БОНУС]" if self.is_bonus else ""
        return f"{self.product.name} x {self.quantity}{bonus_mark}"

    def save(self, *args, **kwargs) -> None:
        """Автоматический расчёт суммы (бонусы = 0)."""
        if self.is_bonus:
            self.total = Decimal('0')
        else:
            self.total = (self.price or Decimal('0')) * (self.quantity or Decimal('0'))

        super().save(*args, **kwargs)


# =============================================================================
# RETURNED ITEMS (v3.0)
# =============================================================================

class ReturnedItem(models.Model):
    """
    Возвращенные товары из заказов (v3.0).

    Для штучных товаров: используется quantity
    Для весовых товаров: quantity=1, weight=вес в кг
    """

    order = models.ForeignKey(
        'StoreOrder',
        on_delete=models.CASCADE,
        related_name='returned_items',
        verbose_name='Заказ'
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='returned_items',
        verbose_name='Товар'
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество',
        help_text='Для штучных: количество шт, для весовых: обычно 1'
    )

    weight = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.1'))],
        verbose_name='Вес (кг)',
        help_text='Только для весовых товаров, шаг 0.1 кг'
    )

    price_at_return = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена на момент возврата',
        help_text='За 1 шт или за 1 кг для весовых'
    )

    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Общая сумма'
    )

    reason = models.TextField(
        blank=True,
        verbose_name='Причина возврата'
    )

    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='returned_items',
        verbose_name='Кто вернул'
    )

    returned_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата возврата'
    )

    class Meta:
        db_table = 'returned_items'
        ordering = ['-returned_at']
        verbose_name = 'Возвращённый товар'
        verbose_name_plural = 'Возвращённые товары'
        indexes = [
            models.Index(fields=['order', 'product']),
            models.Index(fields=['-returned_at']),
        ]

    def __str__(self):
        if self.weight:
            return f"Возврат: {self.product.name} ({self.weight} кг) из заказа #{self.order.id}"
        return f"Возврат: {self.product.name} ({self.quantity} шт) из заказа #{self.order.id}"

    def save(self, *args, **kwargs):
        """
        Автоматический расчёт total_amount.

        Для весовых: (price_at_return / 10) × (weight / 0.1)
        Для штучных: price_at_return × quantity
        """
        if self.product.is_weight_based and self.weight:
            # Весовой товар: цена за 100г × количество 100г
            price_per_100g = self.price_at_return / Decimal('10')
            units_100g = self.weight / Decimal('0.1')
            self.total_amount = price_per_100g * units_100g
        else:
            # Штучный товар
            self.total_amount = self.quantity * self.price_at_return

        super().save(*args, **kwargs)

    def clean(self):
        """Валидация данных."""
        from django.core.exceptions import ValidationError

        # Для весовых товаров обязателен weight
        if self.product and self.product.is_weight_based:
            if not self.weight:
                raise ValidationError({
                    'weight': 'Для весовых товаров обязательно указать вес'
                })

            # Проверка шага 0.1 кг
            if self.weight % Decimal('0.1') != 0:
                raise ValidationError({
                    'weight': 'Вес должен быть кратен 0.1 кг (100 грамм)'
                })

        # Для штучных товаров weight должен быть пустым
        elif self.weight:
            raise ValidationError({
                'weight': 'Штучные товары не имеют веса'
            })


# =============================================================================
# БРАКОВАННЫЕ ТОВАРЫ
# =============================================================================

class DefectiveProduct(models.Model):
    """
    Бракованный товар (ТЗ v2.0).

    Создаётся через:
    - POST /api/stores/{id}/inventory/report-defect/

    ВАЖНО:
    - Брак уменьшает долг магазина
    - Партнёр выбирает товар из инвентаря и отмечает как бракованный
    - Статус сразу APPROVED (партнёр сам выявил)
    """

    class DefectStatus(models.TextChoices):
        PENDING = 'pending', _('Ожидает проверки')
        APPROVED = 'approved', _('Подтверждён')
        REJECTED = 'rejected', _('Отклонён')

    order = models.ForeignKey(
        StoreOrder,
        on_delete=models.CASCADE,
        related_name='defective_products',
        verbose_name='Заказ'
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='defects',
        verbose_name='Товар'
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество'
    )

    # v3.0: Вес для весовых товаров
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.1'))],
        verbose_name='Вес (кг)',
        help_text='Только для весовых товаров'
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена за единицу'
    )

    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Сумма брака',
        help_text='Уменьшит долг магазина'
    )

    status = models.CharField(
        max_length=16,
        choices=DefectStatus.choices,
        default=DefectStatus.PENDING,
        verbose_name='Статус'
    )

    reason = models.TextField(
        blank=True,
        verbose_name='Причина брака'
    )

    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='reported_defects',
        verbose_name='Кто сообщил'
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_defects',
        verbose_name='Кто проверил'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Обновлено'
    )

    class Meta:
        db_table = 'defective_products'
        ordering = ['-created_at']
        verbose_name = 'Бракованный товар'
        verbose_name_plural = 'Бракованные товары'
        indexes = [
            models.Index(fields=['order', '-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self) -> str:
        return f"Брак: {self.product.name} x {self.quantity} ({self.total_amount} сом)"

    def save(self, *args, **kwargs) -> None:
        """
        Автоматический расчёт суммы.

        Для весовых: (price / 10) × (weight / 0.1)
        Для штучных: price × quantity
        """
        if self.product and self.product.is_weight_based and self.weight:
            # Весовой товар: цена за 100г × количество 100г
            price_per_100g = (self.price or Decimal('0')) / Decimal('10')
            units_100g = self.weight / Decimal('0.1')
            self.total_amount = price_per_100g * units_100g
        else:
            # Штучный товар
            self.total_amount = (self.price or Decimal('0')) * (self.quantity or Decimal('0'))
        super().save(*args, **kwargs)


# =============================================================================
# ИСТОРИЯ ЗАКАЗОВ
# =============================================================================

class OrderHistory(models.Model):
    """
    История изменений заказов.

    Логирует все действия: создание, изменение статуса, погашение долга,
    подтверждение брака и т.д.
    """

    order_type = models.CharField(
        max_length=10,
        choices=OrderType.choices,
        verbose_name='Тип заказа'
    )

    order_id = models.PositiveIntegerField(
        verbose_name='ID заказа'
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_history',
        verbose_name='Товар'
    )

    old_status = models.CharField(
        max_length=16,
        blank=True,
        verbose_name='Старый статус'
    )

    new_status = models.CharField(
        max_length=16,
        blank=True,
        verbose_name='Новый статус'
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='order_changes',
        verbose_name='Кто изменил'
    )

    comment = models.TextField(
        blank=True,
        verbose_name='Комментарий'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата'
    )

    class Meta:
        db_table = 'order_history'
        ordering = ['-created_at']
        verbose_name = 'История заказа'
        verbose_name_plural = 'История заказов'
        indexes = [
            models.Index(fields=['order_type', 'order_id']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self) -> str:
        return f"{self.get_order_type_display()} #{self.order_id}: {self.old_status} → {self.new_status}"