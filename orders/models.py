# apps/orders/models.py

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator


class DebtPayment(models.Model):
    order = models.ForeignKey('StoreOrder', on_delete=models.CASCADE, related_name='debt_payments')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    paid_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='debt_payments_made')
    received_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='debt_payments_received')
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Погашение долга'

    def __str__(self) -> str:
        return f"Оплата {self.amount} по заказу #{self.order.id}"


class PartnerOrderStatus(models.TextChoices):
    DRAFT = "draft", _("Черновик")
    PENDING = "pending", _("Ожидает подтверждения")
    CONFIRMED = "confirmed", _("Подтверждён")
    COMPLETED = "completed", _("Завершён")
    CANCELLED = "cancelled", _("Отменён")


class StoreOrderStatus(models.TextChoices):
    DRAFT = "draft", _("Черновик")
    PENDING = "pending", _("Ожидает подтверждения")
    CONFIRMED = "confirmed", _("Подтверждён")
    COMPLETED = "completed", _("Завершён")
    CANCELLED = "cancelled", _("Отменён")


class OrderReturnStatus(models.TextChoices):
    PENDING = "pending", _("На рассмотрении")
    APPROVED = "approved", _("Одобрен")
    REJECTED = "rejected", _("Отклонён")
    CANCELLED = "cancelled", _("Отменён")


class PartnerOrder(models.Model):
    """
    Заказ партнёра (пополнение склада партнёра).
    """

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="partner_orders",
        verbose_name="Партнёр",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_partner_orders",
        null=True,
        blank=True,
        verbose_name="Кем создан",
    )
    status = models.CharField(
        max_length=16,
        choices=PartnerOrderStatus.choices,
        default=PartnerOrderStatus.PENDING,
        verbose_name="Статус",
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        verbose_name="Сумма заказа",
    )
    comment = models.TextField(blank=True, verbose_name="Комментарий")
    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        verbose_name="Idempotency key",
        help_text="Для защиты от повторной отправки заказа с фронта",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменено")

    class Meta:
        db_table = "partner_orders"
        ordering = ["-created_at"]
        verbose_name = "Заказ партнёра"
        verbose_name_plural = "Заказы партнёров"
        indexes = [
            models.Index(fields=["partner", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"PartnerOrder #{self.pk} ({self.partner_id})"

    def recalc_total(self, save: bool = True) -> Decimal:
        total = (
            self.items.aggregate(s=models.Sum("total")).get("s") or Decimal("0")
        )
        self.total_amount = total
        if save:
            self.save(update_fields=["total_amount"])
        return total


class PartnerOrderItem(models.Model):
    """
    Позиция в заказе партнёра.
    """

    order = models.ForeignKey(
        PartnerOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Заказ",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="partner_order_items",
        verbose_name="Товар",
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        validators=[MinValueValidator(0.001)],
        verbose_name="Количество",
    )
    price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Цена",
    )
    total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        verbose_name="Сумма",
    )

    class Meta:
        db_table = "partner_order_items"
        verbose_name = "Позиция заказа партнёра"
        verbose_name_plural = "Позиции заказов партнёров"

    def __str__(self) -> str:
        return f"{self.product} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.total = (self.price or Decimal("0")) * (self.quantity or Decimal("0"))
        super().save(*args, **kwargs)


class StoreOrder(models.Model):
    """
    Заказ магазина у партнёра.
    """

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Магазин",
    )
    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="store_orders",
        verbose_name="Партнёр",
        null=True,
    )
    store_request = models.ForeignKey(
        "stores.StoreRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="store_orders",
        verbose_name="Заявка магазина",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_store_orders",
        verbose_name="Кем создан",
    )
    status = models.CharField(
        max_length=16,
        choices=StoreOrderStatus.choices,
        default=StoreOrderStatus.PENDING,
        verbose_name="Статус",
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        verbose_name="Сумма заказа",
    )
    debt_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        verbose_name="Сумма в долг",
    )
    paid_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        verbose_name="Оплачено",
    )
    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        verbose_name="Idempotency key",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменено")

    class Meta:
        db_table = "store_orders"
        ordering = ["-created_at"]
        verbose_name = "Заказ магазина"
        verbose_name_plural = "Заказы магазинов"
        indexes = [
            models.Index(fields=["store", "created_at"]),
            models.Index(fields=["partner", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"StoreOrder #{self.pk} ({self.store_id})"

    @property
    def outstanding_debt(self) -> Decimal:
        return (self.debt_amount or Decimal("0")) - (self.paid_amount or Decimal("0"))

    def recalc_total(self, save: bool = True) -> Decimal:
        total = (
            self.items.aggregate(s=models.Sum("total")).get("s") or Decimal("0")
        )
        self.total_amount = total
        if save:
            self.save(update_fields=["total_amount"])
        return total

    @property
    def outstanding_debt(self) -> Decimal:
        return (self.debt_amount or Decimal('0')) - (self.paid_amount or Decimal('0'))

    @transaction.atomic
    def pay_debt(self, amount: Decimal, paid_by=None, received_by=None, comment: str = '') -> DebtPayment:
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError('Сумма должна быть больше 0')
        if amount > self.outstanding_debt:
            raise ValidationError(f'Сумма превышает остаток долга: {self.outstanding_debt}')

        self.paid_amount = (self.paid_amount or Decimal('0')) + amount
        self.save(update_fields=['paid_amount'])

        # Обновляем общий долг магазина
        self.store.debt = models.F('debt') - amount
        self.store.save(update_fields=['debt'])

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
    """

    order = models.ForeignKey(
        StoreOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Заказ",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="store_order_items",
        verbose_name="Товар",
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        validators=[MinValueValidator(0.001)],
        verbose_name="Количество",
    )
    price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Цена",
    )
    total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        verbose_name="Сумма",
    )
    is_bonus = models.BooleanField(
        default=False, verbose_name="Бонусная позиция"
    )

    class Meta:
        db_table = "store_order_items"
        verbose_name = "Позиция заказа магазина"
        verbose_name_plural = "Позиции заказов магазинов"

    def __str__(self) -> str:
        return f"{self.product} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.total = (self.price or Decimal("0")) * (self.quantity or Decimal("0"))
        super().save(*args, **kwargs)


class OrderReturn(models.Model):
    """
    Возврат товара по заказу магазина.
    """

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="order_returns",
        verbose_name="Магазин",
        null=True,
    )
    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="order_returns",
        verbose_name="Партнёр",
        null=True,
    )
    order = models.ForeignKey(
        StoreOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="returns",
        verbose_name="Заказ магазина",
    )
    status = models.CharField(
        max_length=16,
        choices=OrderReturnStatus.choices,
        default=OrderReturnStatus.PENDING,
        verbose_name="Статус",
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        verbose_name="Сумма возврата",
    )
    reason = models.TextField(blank=True, verbose_name="Причина")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_order_returns",
        verbose_name="Кем создан",
    )
    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        verbose_name="Idempotency key",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменено")

    class Meta:
        db_table = "order_returns"
        ordering = ["-created_at"]
        verbose_name = "Возврат по заказу"
        verbose_name_plural = "Возвраты по заказам"
        indexes = [
            models.Index(fields=["store", "created_at"]),
            models.Index(fields=["partner", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"OrderReturn #{self.pk}"

    def recalc_total(self, save: bool = True) -> Decimal:
        total = (
            self.items.aggregate(s=models.Sum("total")).get("s") or Decimal("0")
        )
        self.total_amount = total
        if save:
            self.save(update_fields=["total_amount"])
        return total


class OrderReturnItem(models.Model):
    """
    Позиция возврата по заказу магазина.
    """

    order_return = models.ForeignKey(
        OrderReturn,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Возврат",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="order_return_items",
        verbose_name="Товар",
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        validators=[MinValueValidator(0.001)],
        verbose_name="Количество",
    )
    price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Цена",
    )
    total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        verbose_name="Сумма",
    )
    reason = models.CharField(
        max_length=255, blank=True, verbose_name="Причина по позиции"
    )

    class Meta:
        db_table = "order_return_items"
        verbose_name = "Позиция возврата по заказу"
        verbose_name_plural = "Позиции возвратов по заказам"

    def __str__(self) -> str:
        return f"{self.product} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.total = (self.price or Decimal("0")) * (self.quantity or Decimal("0"))
        super().save(*args, **kwargs)


class OrderType(models.TextChoices):
    PARTNER = "partner", "Заказ партнёра"
    STORE = "store", "Заказ магазина"
    RETURN = "return", "Возврат по заказу"


class OrderHistory(models.Model):
    """
    История смены статусов заказов и возвратов.
    """

    order_type = models.CharField(
        max_length=16,
        choices=OrderType.choices,
        verbose_name="Тип объекта",
        null=True
    )
    order_id = models.PositiveIntegerField(verbose_name="ID объекта")
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_history_entries",
        verbose_name="Товар (опционально)",
    )
    old_status = models.CharField(
        max_length=16, blank=True, verbose_name="Старый статус"
    )
    new_status = models.CharField(
        max_length=16, verbose_name="Новый статус", null=True
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_history_entries",
        verbose_name="Кем изменён",
    )
    comment = models.TextField(blank=True, verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        db_table = "order_history"
        ordering = ["-created_at"]
        verbose_name = "История заказа"
        verbose_name_plural = "История заказов"
        indexes = [
            models.Index(fields=["order_type", "order_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.order_type}:{self.order_id} {self.old_status}->{self.new_status}"

