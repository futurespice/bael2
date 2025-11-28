# apps/stores/models.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2
"""
Модели модуля stores.

Изменения:
- Добавлено поле total_paid в Store для отслеживания погашенного долга
- StoreSelection с unique_together для предотвращения дублей
- Улучшенные валидаторы и индексы
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models


class Region(models.Model):
    """Регион/Область Кыргызстана."""

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Название'
    )

    class Meta:
        db_table = 'regions'
        verbose_name = 'Регион'
        verbose_name_plural = 'Регионы'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class City(models.Model):
    """Город."""

    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
        related_name='cities',
        verbose_name='Регион'
    )
    name = models.CharField(max_length=100, verbose_name='Название')

    class Meta:
        db_table = 'cities'
        verbose_name = 'Город'
        verbose_name_plural = 'Города'
        ordering = ['region', 'name']
        unique_together = ['region', 'name']

    def __str__(self) -> str:
        return f"{self.name} ({self.region.name})"


class Store(models.Model):
    """
    Магазин - общая сущность.

    По ТЗ:
    - База магазинов общая для всех партнёров
    - Поиск по ИНН (12-14 цифр)
    - Статусы: активный / деактивированный (заморожен админом)
    - При заморозке нельзя взаимодействовать, даже погасить долг
    """

    # Валидаторы
    inn_regex = RegexValidator(
        regex=r'^\d{12,14}$',
        message='ИНН должен содержать от 12 до 14 цифр'
    )
    phone_regex = RegexValidator(
        regex=r'^\+996\d{9}$',
        message='Формат телефона: +996XXXXXXXXX'
    )

    APPROVAL_STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('approved', 'Одобрен'),
        ('rejected', 'Отклонён'),
    ]

    # === Основная информация ===
    name = models.CharField(
        max_length=200,
        verbose_name='Название магазина'
    )
    inn = models.CharField(
        max_length=14,
        validators=[inn_regex],
        unique=True,
        verbose_name='ИНН',
        db_index=True
    )
    owner_name = models.CharField(
        max_length=200,
        verbose_name='ФИО владельца'
    )
    phone = models.CharField(
        max_length=13,
        validators=[phone_regex],
        verbose_name='Телефон',
        db_index=True
    )

    # === Местоположение ===
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name='stores',
        verbose_name='Регион'
    )
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        related_name='stores',
        verbose_name='Город'
    )
    address = models.CharField(
        max_length=250,
        verbose_name='Адрес'
    )
    latitude = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Широта'
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Долгота'
    )

    # === Финансы ===
    debt = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Текущий долг'
    )
    total_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Всего погашено'
    )

    # === Статусы ===
    approval_status = models.CharField(
        max_length=20,
        choices=APPROVAL_STATUS_CHOICES,
        default='pending',
        verbose_name='Статус одобрения',
        db_index=True
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен (не заморожен)',
        db_index=True,
        help_text='При деактивации партнёры не могут взаимодействовать с магазином'
    )

    # === Системные поля ===
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_stores',
        verbose_name='Создал'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )

    class Meta:
        db_table = 'stores'
        verbose_name = 'Магазин'
        verbose_name_plural = 'Магазины'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['inn']),
            models.Index(fields=['phone']),
            models.Index(fields=['region', 'city']),
            models.Index(fields=['debt']),
            models.Index(fields=['is_active', 'approval_status']),
        ]

    def __str__(self) -> str:
        return f"{self.name} (ИНН: {self.inn})"

    def clean(self) -> None:
        """Валидация: город должен принадлежать выбранному региону."""
        if self.city and self.region and self.city.region_id != self.region_id:
            raise ValidationError({
                'city': 'Город должен принадлежать выбранному региону'
            })

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    # === Бизнес-методы ===

    def check_can_interact(self) -> None:
        """
        Проверка возможности взаимодействия с магазином.
        Вызывает ValidationError если магазин заморожен или не одобрен.
        """
        if not self.is_active:
            raise ValidationError(
                'Магазин деактивирован. Взаимодействие невозможно.'
            )
        if self.approval_status != 'approved':
            raise ValidationError(
                'Магазин не одобрен. Взаимодействие невозможно.'
            )

    def freeze(self) -> None:
        """Заморозить магазин (деактивировать)."""
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])

    def unfreeze(self) -> None:
        """Разморозить магазин (активировать)."""
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])

    @property
    def is_frozen(self) -> bool:
        """Проверка: заморожен ли магазин."""
        return not self.is_active

    @property
    def can_interact(self) -> bool:
        """Можно ли взаимодействовать с магазином."""
        return self.is_active and self.approval_status == 'approved'


class StoreSelection(models.Model):
    """
    Выбор магазина пользователем с ролью STORE.

    По ТЗ: пользователь может выбрать магазин для работы от его имени.
    После выбора доступен CRUD профиля через /stores/profile/
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'store'},
        related_name='store_selections',
        verbose_name='Пользователь'
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='selections',
        verbose_name='Магазин'
    )
    is_current = models.BooleanField(
        default=True,
        verbose_name='Текущий выбор',
        help_text='Активный магазин для пользователя'
    )
    selected_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата выбора'
    )

    class Meta:
        db_table = 'store_selections'
        verbose_name = 'Выбор магазина'
        verbose_name_plural = 'Выборы магазинов'
        # ИСПРАВЛЕНИЕ: unique_together для предотвращения дублей
        unique_together = ['user', 'store']
        indexes = [
            models.Index(fields=['user', 'is_current']),
        ]

    def __str__(self) -> str:
        current = " [ТЕКУЩИЙ]" if self.is_current else ""
        return f"{self.user.get_full_name()} → {self.store.name}{current}"

    def save(self, *args, **kwargs) -> None:
        """При установке is_current=True, сбрасываем у других."""
        if self.is_current:
            StoreSelection.objects.filter(
                user=self.user,
                is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)


class StoreProductRequest(models.Model):
    """
    Wishlist магазина - временный список желаемых товаров.

    По ТЗ:
    - НЕ влияет на инвентарь, пока партнёр не создаст заказ
    - НЕ создаёт долг
    - Магазин может отменить до момента создания заказа
    """

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='product_requests',
        verbose_name='Магазин'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='store_requests',
        verbose_name='Товар'
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.1'))],
        verbose_name='Количество'
    )
    note = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Примечание'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )

    class Meta:
        db_table = 'store_product_requests'
        verbose_name = 'Wishlist товар'
        verbose_name_plural = 'Wishlist товары'
        unique_together = ['store', 'product']
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.store.name} → {self.product.name}: {self.quantity}"

    @property
    def total(self) -> Decimal:
        """Расчётная стоимость позиции."""
        if self.product and self.product.price:
            return self.quantity * self.product.price
        return Decimal('0')


class StoreRequest(models.Model):
    """
    Снимок wishlist'а магазина (история запросов).

    Создаётся из StoreProductRequest когда магазин "отправляет" запрос.
    Партнёр видит этот запрос и может создать заказ на его основе.
    """

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='requests',
        verbose_name='Магазин'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_store_requests',
        verbose_name='Создал'
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Общая сумма'
    )
    note = models.TextField(
        blank=True,
        verbose_name='Примечание'
    )
    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        verbose_name='Ключ идемпотентности',
        help_text='Защита от повторной отправки'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )

    class Meta:
        db_table = 'store_requests'
        verbose_name = 'Запрос магазина'
        verbose_name_plural = 'Запросы магазинов'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['store', 'created_at']),
            models.Index(fields=['idempotency_key']),
        ]

    def __str__(self) -> str:
        return f"Запрос #{self.id} от {self.store.name} ({self.total_amount} сом)"


class StoreRequestItem(models.Model):
    """Позиция в запросе магазина."""

    request = models.ForeignKey(
        StoreRequest,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Запрос'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='request_items',
        verbose_name='Товар'
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.1'))],
        verbose_name='Количество'
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена за единицу'
    )
    is_cancelled = models.BooleanField(
        default=False,
        verbose_name='Отменено'
    )

    class Meta:
        db_table = 'store_request_items'
        verbose_name = 'Позиция запроса'
        verbose_name_plural = 'Позиции запросов'

    def __str__(self) -> str:
        status = " [ОТМЕНЕНО]" if self.is_cancelled else ""
        return f"{self.product.name}: {self.quantity}{status}"

    @property
    def total(self) -> Decimal:
        """Общая стоимость позиции."""
        return self.quantity * self.price


class StoreInventory(models.Model):
    """Инвентарь магазина (товары на складе магазина)."""

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='inventory',
        verbose_name='Магазин'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='store_inventory',
        verbose_name='Товар'
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Количество'
    )
    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name='Последнее обновление'
    )

    class Meta:
        db_table = 'store_inventory'
        verbose_name = 'Инвентарь магазина'
        verbose_name_plural = 'Инвентарь магазинов'
        unique_together = ['store', 'product']

    def __str__(self) -> str:
        return f"{self.store.name} - {self.product.name}: {self.quantity}"

    @property
    def total_price(self) -> Decimal:
        """Общая стоимость товара в инвентаре."""
        if self.product and self.product.price:
            return self.quantity * self.product.price
        return Decimal('0')


class PartnerInventory(models.Model):
    """Инвентарь партнёра (личный склад партнёра)."""

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'partner'},
        related_name='inventory',
        verbose_name='Партнёр'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='partner_inventory',
        verbose_name='Товар'
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Количество'
    )
    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name='Последнее обновление'
    )

    class Meta:
        db_table = 'partner_inventory'
        verbose_name = 'Инвентарь партнёра'
        verbose_name_plural = 'Инвентарь партнёров'
        unique_together = ['partner', 'product']

    def __str__(self) -> str:
        return f"{self.partner.get_full_name()} - {self.product.name}: {self.quantity}"

    @property
    def total_price(self) -> Decimal:
        """Общая стоимость товара."""
        if self.product and self.product.price:
            return self.quantity * self.product.price
        return Decimal('0')


class ReturnRequest(models.Model):
    """
    Запрос на возврат товаров от партнёра к админу.

    По ТЗ 2.4: Возврат НЕ требует подтверждения от админа.
    """

    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('completed', 'Завершён'),
        ('cancelled', 'Отменён'),
    ]

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='return_requests',
        limit_choices_to={'role': 'partner'},
        verbose_name='Партнёр'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='Статус'
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Сумма возврата'
    )
    reason = models.TextField(
        blank=True,
        verbose_name='Причина возврата'
    )
    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        verbose_name='Ключ идемпотентности'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата завершения'
    )

    class Meta:
        db_table = 'return_requests'
        verbose_name = 'Возврат товаров'
        verbose_name_plural = 'Возвраты товаров'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['partner', 'created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self) -> str:
        return f"Возврат #{self.id} от {self.partner.get_full_name()}"


class ReturnRequestItem(models.Model):
    """Позиция в запросе на возврат."""

    request = models.ForeignKey(
        ReturnRequest,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Запрос'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='return_items',
        verbose_name='Товар'
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.1'))],
        verbose_name='Количество'
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена за единицу'
    )

    class Meta:
        db_table = 'return_request_items'
        verbose_name = 'Позиция возврата'
        verbose_name_plural = 'Позиции возвратов'

    def __str__(self) -> str:
        return f"{self.product.name}: {self.quantity}"

    @property
    def total(self) -> Decimal:
        """Общая стоимость позиции."""
        return self.quantity * self.price
