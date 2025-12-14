# apps/orders/models.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Модели заказов согласно ТЗ v2.0.

КЛЮЧЕВЫЕ ИЗМЕНЕНИЯ v2.0:
1. Новый workflow: Магазин → Админ → Партнёр
2. Статусы StoreOrder: pending, in_transit, accepted, rejected
3. Partner может быть NULL при создании заказа
4. Добавлены поля: prepayment_amount, reviewed_by, confirmed_by
5. Инвентарь магазина обновляется при одобрении админом
6. Партнёр может удалить товары из инвентаря при подтверждении
7. Добавлена модель DefectiveProduct для бракованных товаров

МОДЕЛИ:
- StoreOrder: Заказ магазина (основной workflow)
- StoreOrderItem: Позиция заказа магазина
- PartnerOrder: Заказ партнёра у админа (пополнение склада)
- PartnerOrderItem: Позиция заказа партнёра
- DebtPayment: Погашение долга
- DefectiveProduct: Бракованные товары
- OrderHistory: История изменений заказов
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


class PartnerOrderStatus(models.TextChoices):
    """Статусы заказа партнёра у админа (пополнение склада)."""
    PENDING = 'pending', _('В ожидании')
    CONFIRMED = 'confirmed', _('Подтверждён')
    CANCELLED = 'cancelled', _('Отменён')


class OrderType(models.TextChoices):
    """Типы заказов для истории."""
    STORE = 'store', _('Заказ магазина')
    PARTNER = 'partner', _('Заказ партнёра')


# =============================================================================
# ПОГАШЕНИЕ ДОЛГОВ
# =============================================================================

class DebtPayment(models.Model):
    """
    Погашение долга по заказу магазина.

    Создаётся партнёром или админом при погашении долга.
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

    НОВЫЙ WORKFLOW:
    1. Магазин создаёт заказ → status=PENDING, partner=NULL
    2. Админ одобряет → status=IN_TRANSIT, товары → инвентарь магазина
    3. Партнёр подтверждает → status=ACCEPTED, создаётся долг

    ВАЖНО:
    - Partner может быть NULL при создании
    - Товары добавляются в инвентарь при одобрении админом
    - Долг создаётся при подтверждении партнёром
    - Предоплата уменьшает долг
    """

    # === Основные связи ===
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        related_name='orders',
        verbose_name='Магазин'
    )

    # КРИТИЧНО: partner NULL при создании
    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='confirmed_store_orders',
        limit_choices_to={'role': 'partner'},
        null=True,
        blank=True,
        verbose_name='Партнёр',
        help_text='Назначается при переходе в статус IN_TRANSIT'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_store_orders',
        verbose_name='Создал'
    )

    # === Статус и workflow ===
    status = models.CharField(
        max_length=16,
        choices=StoreOrderStatus.choices,
        default=StoreOrderStatus.PENDING,
        verbose_name='Статус',
        db_index=True
    )

    # === Финансы ===
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Сумма заказа'
    )

    # НОВОЕ: предоплата (ТЗ v2.0)
    prepayment_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Предоплата',
        help_text='Указывает партнёр при подтверждении'
    )

    debt_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Сумма в долг',
        help_text='Автоматически: total_amount - prepayment_amount'
    )

    paid_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Оплачено'
    )

    # === Участники workflow ===
    # НОВОЕ: админ, который одобрил/отклонил
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_orders',
        limit_choices_to={'role': 'admin'},
        verbose_name='Проверил (админ)'
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата проверки'
    )

    # НОВОЕ: партнёр, который подтвердил
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='partner_confirmations',
        limit_choices_to={'role': 'partner'},
        verbose_name='Подтвердил (партнёр)'
    )

    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата подтверждения'
    )

    # === Системные поля ===
    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        verbose_name='Idempotency key',
        help_text='Защита от повторной отправки'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Создано'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Обновлено'
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
        return f"Заказ #{self.pk}: {self.store.name} ({self.get_status_display()})"

    def clean(self) -> None:
        """Валидация заказа."""
        super().clean()

        # Предоплата не может превышать сумму
        if self.prepayment_amount > self.total_amount:
            raise ValidationError({
                'prepayment_amount': f'Предоплата ({self.prepayment_amount}) '
                                     f'не может превышать сумму заказа ({self.total_amount})'
            })

    # === Свойства ===

    @property
    def outstanding_debt(self) -> Decimal:
        """Остаток долга (долг минус оплачено)."""
        return (self.debt_amount or Decimal('0')) - (self.paid_amount or Decimal('0'))

    @property
    def is_fully_paid(self) -> bool:
        """Полностью ли оплачен долг."""
        return self.outstanding_debt <= Decimal('0')

    # === Бизнес-методы ===

    def recalc_total(self, save: bool = True) -> Decimal:
        """
        Пересчитать сумму заказа из позиций.

        Args:
            save: Сохранить в БД

        Returns:
            Новая сумма заказа
        """
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
        Погасить долг по заказу (частично или полностью).

        Args:
            amount: Сумма погашения
            paid_by: Кто оплатил
            received_by: Кто принял оплату
            comment: Комментарий

        Returns:
            DebtPayment

        Raises:
            ValidationError: Если сумма некорректна
        """
        amount = Decimal(str(amount))

        if amount <= Decimal('0'):
            raise ValidationError('Сумма должна быть больше 0')

        if amount > self.outstanding_debt:
            raise ValidationError(
                f'Сумма превышает остаток долга: {self.outstanding_debt} сом'
            )

        # Обновляем оплаченную сумму
        self.paid_amount = (self.paid_amount or Decimal('0')) + amount
        self.save(update_fields=['paid_amount'])

        # Обновляем долг магазина
        Store.objects.filter(pk=self.store.pk).update(
            debt=models.F('debt') - amount,
            total_paid=models.F('total_paid') + amount
        )
        self.store.refresh_from_db()

        # Создаём запись о погашении
        payment = DebtPayment.objects.create(
            order=self,
            amount=amount,
            paid_by=paid_by,
            received_by=received_by,
            comment=comment
        )

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=self.id,
            old_status=self.status,
            new_status=self.status,
            changed_by=paid_by,
            comment=f'Погашение долга на {amount} сом'
        )

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
# ЗАКАЗЫ ПАРТНЁРОВ (пополнение склада у админа)
# =============================================================================

class PartnerOrder(models.Model):
    """
    Заказ партнёра у админа для пополнения склада.

    Это НЕ основной workflow. Партнёр запрашивает товары у админа,
    чтобы потом продавать магазинам.
    """

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='partner_orders',
        limit_choices_to={'role': 'partner'},
        verbose_name='Партнёр'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_partner_orders',
        verbose_name='Создал'
    )

    status = models.CharField(
        max_length=16,
        choices=PartnerOrderStatus.choices,
        default=PartnerOrderStatus.PENDING,
        verbose_name='Статус'
    )

    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Сумма заказа'
    )

    comment = models.TextField(
        blank=True,
        verbose_name='Комментарий'
    )

    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        verbose_name='Idempotency key'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Создано'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Обновлено'
    )

    class Meta:
        db_table = 'partner_orders'
        ordering = ['-created_at']
        verbose_name = 'Заказ партнёра'
        verbose_name_plural = 'Заказы партнёров'
        indexes = [
            models.Index(fields=['partner', '-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self) -> str:
        return f"Заказ партнёра #{self.pk} ({self.get_status_display()})"

    def recalc_total(self, save: bool = True) -> Decimal:
        """Пересчитать сумму заказа."""
        total = self.items.aggregate(
            s=models.Sum('total')
        ).get('s') or Decimal('0')

        self.total_amount = total

        if save:
            self.save(update_fields=['total_amount'])

        return total


class PartnerOrderItem(models.Model):
    """Позиция в заказе партнёра."""

    order = models.ForeignKey(
        PartnerOrder,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Заказ'
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.PROTECT,
        related_name='partner_order_items',
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
        verbose_name='Цена'
    )

    total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Сумма'
    )

    class Meta:
        db_table = 'partner_order_items'
        verbose_name = 'Позиция заказа партнёра'
        verbose_name_plural = 'Позиции заказов партнёров'

    def __str__(self) -> str:
        return f"{self.product.name} x {self.quantity}"

    def save(self, *args, **kwargs) -> None:
        """Автоматический расчёт суммы."""
        self.total = (self.price or Decimal('0')) * (self.quantity or Decimal('0'))
        super().save(*args, **kwargs)


# =============================================================================
# БРАКОВАННЫЕ ТОВАРЫ
# =============================================================================

class DefectiveProduct(models.Model):
    """
    Бракованный товар (ТЗ v2.0).

    Магазин заявляет о браке → Партнёр выбирает из инвентаря →
    Уменьшается долг магазина.

    ВАЖНО:
    - Брак уменьшает долг магазина
    - Партнёр может отметить товар как бракованный
    - Весовые товары: фиксируется вес и сумма
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

    @transaction.atomic
    def approve(self, approved_by: 'User') -> None:
        """
        Подтвердить брак → уменьшить долг магазина.

        Args:
            approved_by: Кто подтвердил (партнёр)
        """
        if self.status != self.DefectStatus.PENDING:
            raise ValidationError('Можно подтвердить только заявки в статусе "Ожидает"')

        # Уменьшаем долг заказа
        StoreOrder.objects.filter(pk=self.order.pk).update(
            debt_amount=models.F('debt_amount') - self.total_amount
        )
        self.order.refresh_from_db()

        Store.objects.filter(pk=self.order.store.pk).update(
            debt=models.F('debt') - self.total_amount
        )
        self.order.store.refresh_from_db()

        # Обновляем статус
        self.status = self.DefectStatus.APPROVED
        self.reviewed_by = approved_by
        self.save(update_fields=['status', 'reviewed_by', 'updated_at'])

        # История
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=self.order.id,
            old_status=self.order.status,
            new_status=self.order.status,
            changed_by=approved_by,
            comment=f'Подтверждён брак на {self.total_amount} сом'
        )


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
        max_length=16,
        choices=OrderType.choices,
        default='store_order',
        verbose_name='Тип объекта'
    )

    order_id = models.PositiveIntegerField(
        verbose_name='ID объекта'
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_history_entries',
        verbose_name='Товар (опционально)'
    )

    old_status = models.CharField(
        max_length=16,
        blank=True,
        verbose_name='Старый статус'
    )

    new_status = models.CharField(
        max_length=16,
        blank=True,
        default='',
        verbose_name='Новый статус'
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_history_entries',
        verbose_name='Кем изменён'
    )

    comment = models.TextField(
        blank=True,
        verbose_name='Комментарий'
    )

    created_at = models.DateTimeField(
        default=timezone.now,
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
        return f"{self.order_type}:{self.order_id} {self.old_status}→{self.new_status}"