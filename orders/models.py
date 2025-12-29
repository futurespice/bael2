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
        on_delete=models.PROTECT,
        related_name='store_order_items',
        verbose_name='Товар'
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество'
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
        on_delete=models.PROTECT,
        related_name='defects',
        verbose_name='Товар'
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество'
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
        """Автоматический расчёт суммы."""
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
