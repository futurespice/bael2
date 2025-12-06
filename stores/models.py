# apps/stores/models.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Модели для управления магазинами согласно ТЗ v2.0.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. Магазины автоматически одобряются (approval_status='approved' по умолчанию)
2. Добавлены методы get_cities_count(), get_stores_count() в Region и City
3. Убрана необходимость ручного одобрения магазинов
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# =============================================================================
# ГЕОГРАФИЯ
# =============================================================================

class Region(models.Model):
    """Регион/Область Кыргызстана."""

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Название области'
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )

    class Meta:
        db_table = 'regions'
        verbose_name = 'Регион'
        verbose_name_plural = 'Регионы'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name

    def get_cities_count(self) -> int:
        """
        Количество городов в регионе.
        
        Returns:
            int: Количество городов
        """
        return self.cities.count()

    def get_stores_count(self) -> int:
        """
        Количество магазинов в регионе.
        
        Returns:
            int: Количество магазинов
        """
        return self.stores.count()


class City(models.Model):
    """Город Кыргызстана."""

    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
        related_name='cities',
        verbose_name='Регион'
    )
    name = models.CharField(
        max_length=100,
        verbose_name='Название города'
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )

    class Meta:
        db_table = 'cities'
        verbose_name = 'Город'
        verbose_name_plural = 'Города'
        ordering = ['region__name', 'name']
        unique_together = ['region', 'name']
        indexes = [
            models.Index(fields=['region', 'name']),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.region.name})"

    def get_stores_count(self) -> int:
        """
        Количество магазинов в городе.
        
        Returns:
            int: Количество магазинов
        """
        return self.stores.count()


# =============================================================================
# МАГАЗИН
# =============================================================================

class Store(models.Model):
    """
    Магазин - центральная сущность системы.

    БИЗНЕС-ЛОГИКА (ТЗ v2.0):
    1. Общая база магазинов для всех пользователей role='store'
    2. Пользователь выбирает магазин через StoreSelection
    3. Магазин автоматически одобряется при создании (approval_status='approved')
    4. Магазин может быть заблокирован админом (is_active=False)
    5. ИНН - уникальный идентификатор (12-14 цифр)
    6. Поиск по: ИНН, название, город
    7. Фильтрация по: город, область

    ФИНАНСЫ:
    - debt: Текущий непогашенный долг
    - total_paid: Всего погашено за всё время
    - Долг создаётся при подтверждении заказа партнёром
    - Долг может быть отрицательным (переплата)
    """

    # === Валидаторы ===
    inn_validator = RegexValidator(
        regex=r'^\d{12,14}$',
        message='ИНН должен содержать от 12 до 14 цифр'
    )
    phone_validator = RegexValidator(
        regex=r'^\+996\d{9}$',
        message='Формат телефона: +996XXXXXXXXX (9 цифр после +996)'
    )

    # === Статусы одобрения ===
    class ApprovalStatus(models.TextChoices):
        PENDING = 'pending', _('Ожидает одобрения')
        APPROVED = 'approved', _('Одобрен')
        REJECTED = 'rejected', _('Отклонён')

    # === Основная информация ===
    name = models.CharField(
        max_length=200,
        verbose_name='Название магазина',
        db_index=True,
        help_text='Используется для поиска'
    )

    inn = models.CharField(
        max_length=14,
        validators=[inn_validator],
        unique=True,
        verbose_name='ИНН',
        db_index=True,
        help_text='Уникальный идентификатор магазина (12-14 цифр)'
    )

    owner_name = models.CharField(
        max_length=200,
        verbose_name='ФИО владельца магазина',
        db_index=True,
        help_text='Используется для поиска'
    )

    phone = models.CharField(
        max_length=13,
        validators=[phone_validator],
        verbose_name='Телефон магазина',
        db_index=True
    )

    # === Местоположение ===
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name='stores',
        verbose_name='Область',
        help_text='Используется для фильтрации'
    )

    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        related_name='stores',
        verbose_name='Город',
        help_text='Используется для фильтрации и поиска'
    )

    address = models.CharField(
        max_length=250,
        verbose_name='Адрес магазина'
    )

    # GPS координаты (опционально)
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
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Текущий долг',
        help_text='Может быть отрицательным (переплата)',
        db_index=True
    )

    total_paid = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Всего погашено',
        help_text='Сумма всех погашений за всё время'
    )

    # === Статусы ===
    # ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: default=APPROVED (по требованию #2)
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.APPROVED,  # ✅ Автоматическое одобрение
        verbose_name='Статус одобрения',
        db_index=True,
        help_text='Магазины автоматически одобряются при создании'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен (не заблокирован)',
        db_index=True,
        help_text='Заблокированный магазин не может создавать/получать заказы'
    )

    # === Системные поля ===
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_stores',
        verbose_name='Создал (пользователь)'
    )

    created_at = models.DateTimeField(
        default=timezone.now,
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
            models.Index(fields=['name']),
            models.Index(fields=['owner_name']),
            models.Index(fields=['phone']),
            models.Index(fields=['region', 'city']),
            models.Index(fields=['debt']),
            models.Index(fields=['is_active', 'approval_status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self) -> str:
        return f"{self.name} (ИНН: {self.inn})"

    def clean(self) -> None:
        """
        Валидация модели.

        Проверки:
        1. Город принадлежит выбранному региону
        2. ИНН содержит только цифры
        """
        super().clean()

        # Проверка: город принадлежит региону
        if self.city and self.region and self.city.region_id != self.region_id:
            raise ValidationError({
                'city': f'Город {self.city.name} не принадлежит региону {self.region.name}'
            })

        # Проверка: ИНН только цифры
        if self.inn and not self.inn.isdigit():
            raise ValidationError({
                'inn': 'ИНН должен содержать только цифры'
            })

    def save(self, *args, **kwargs) -> None:
        """Сохранение с валидацией."""
        self.full_clean()
        super().save(*args, **kwargs)

    # === Бизнес-методы ===

    @property
    def can_interact(self) -> bool:
        """
        Проверка: можно ли взаимодействовать с магазином.

        Returns:
            True если магазин активен И одобрен
        """
        return self.is_active and self.approval_status == self.ApprovalStatus.APPROVED

    def check_can_interact(self) -> None:
        """
        Проверка возможности взаимодействия.

        Raises:
            ValidationError: Если магазин заблокирован или не одобрен
        """
        if not self.is_active:
            raise ValidationError(
                f"Магазин '{self.name}' заблокирован админом. "
                f"Взаимодействие невозможно."
            )

        if self.approval_status != self.ApprovalStatus.APPROVED:
            raise ValidationError(
                f"Магазин '{self.name}' не одобрен (статус: {self.get_approval_status_display()}). "
                f"Взаимодействие невозможно."
            )

    @transaction.atomic
    def freeze(self, *, frozen_by: Optional['User'] = None) -> None:
        """
        Заморозить магазин (заблокировать).

        Args:
            frozen_by: Кто заблокировал (обычно админ)
        """
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])

    @transaction.atomic
    def unfreeze(self, *, unfrozen_by: Optional['User'] = None) -> None:
        """
        Разморозить магазин (активировать).

        Args:
            unfrozen_by: Кто разблокировал (обычно админ)
        """
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])

    @transaction.atomic
    def approve(self, *, approved_by: Optional['User'] = None) -> None:
        """
        Одобрить магазин.

        Args:
            approved_by: Кто одобрил (админ)
        """
        self.approval_status = self.ApprovalStatus.APPROVED
        self.save(update_fields=['approval_status', 'updated_at'])

    @transaction.atomic
    def reject(self, *, rejected_by: Optional['User'] = None, reason: str = '') -> None:
        """
        Отклонить магазин.

        Args:
            rejected_by: Кто отклонил (админ)
            reason: Причина отклонения
        """
        self.approval_status = self.ApprovalStatus.REJECTED
        self.save(update_fields=['approval_status', 'updated_at'])

    @property
    def is_frozen(self) -> bool:
        """Проверка: заблокирован ли магазин."""
        return not self.is_active

    @property
    def is_approved(self) -> bool:
        """Проверка: одобрен ли магазин."""
        return self.approval_status == self.ApprovalStatus.APPROVED

    @property
    def outstanding_debt(self) -> Decimal:
        """Текущий непогашенный долг (алиас для debt)."""
        return self.debt

    @property
    def has_debt(self) -> bool:
        """Проверка: есть ли долг."""
        return self.debt > Decimal('0')

    def get_total_orders_count(self) -> int:
        """Общее количество заказов магазина."""
        return self.orders.count()

    def get_accepted_orders_count(self) -> int:
        """Количество принятых заказов."""
        from orders.models import StoreOrderStatus
        return self.orders.filter(status=StoreOrderStatus.ACCEPTED).count()

    def get_inventory_items_count(self) -> int:
        """Количество позиций в инвентаре."""
        return self.inventory.count()

    def get_users_count(self) -> int:
        """Количество пользователей, работающих в магазине."""
        return self.selections.filter(is_current=True).count()


# =============================================================================
# ВЫБОР МАГАЗИНА ПОЛЬЗОВАТЕЛЕМ
# =============================================================================

class StoreSelection(models.Model):
    """
    Выбор магазина пользователем с role='store'.

    БИЗНЕС-ЛОГИКА (ТЗ v2.0):
    1. Один пользователь может быть только в ОДНОМ магазине одновременно
    2. Несколько пользователей могут быть в ОДНОМ магазине одновременно
    3. При выборе нового магазина старый автоматически становится is_current=False
    4. Пользователь может выйти из магазина и выбрать другой
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
        db_index=True,
        help_text='Активный магазин для пользователя. Только один может быть True.'
    )

    selected_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата выбора'
    )

    deselected_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата отмены выбора'
    )

    class Meta:
        db_table = 'store_selections'
        verbose_name = 'Выбор магазина'
        verbose_name_plural = 'Выборы магазинов'
        ordering = ['-selected_at']
        unique_together = ['user', 'store']
        indexes = [
            models.Index(fields=['user', 'is_current']),
            models.Index(fields=['store', 'is_current']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_current=True),
                name='unique_current_store_per_user'
            )
        ]

    def __str__(self) -> str:
        status = " [ТЕКУЩИЙ]" if self.is_current else " [НЕАКТИВНЫЙ]"
        return f"{self.user.get_full_name()} → {self.store.name}{status}"

    def clean(self) -> None:
        """Валидация выбора магазина."""
        super().clean()

        if self.user.role != 'store':
            raise ValidationError({
                'user': 'Только пользователи с ролью "Магазин" могут выбирать магазины'
            })

        if self.store.approval_status != Store.ApprovalStatus.APPROVED:
            raise ValidationError({
                'store': f'Магазин "{self.store.name}" не одобрен. Выбор невозможен.'
            })

        if not self.store.is_active:
            raise ValidationError({
                'store': f'Магазин "{self.store.name}" заблокирован. Выбор невозможен.'
            })

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        """Сохранение с автоматическим сбросом других активных выборов."""
        if self.is_current:
            StoreSelection.objects.filter(
                user=self.user,
                is_current=True
            ).exclude(pk=self.pk).update(
                is_current=False,
                deselected_at=timezone.now()
            )

        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def get_current_store_for_user(cls, user: 'User') -> Optional[Store]:
        """Получить текущий активный магазин пользователя."""
        selection = cls.objects.filter(
            user=user,
            is_current=True
        ).select_related('store').first()

        return selection.store if selection else None

    @classmethod
    @transaction.atomic
    def select_store(cls, *, user: 'User', store: Store) -> 'StoreSelection':
        """Выбрать магазин для пользователя."""
        if user.role != 'store':
            raise ValidationError('Только пользователи с ролью "Магазин" могут выбирать магазины')

        store.check_can_interact()

        selection, created = cls.objects.get_or_create(
            user=user,
            store=store,
            defaults={'is_current': True}
        )

        if not created and not selection.is_current:
            selection.is_current = True
            selection.save()

        return selection

    @classmethod
    @transaction.atomic
    def deselect_current_store(cls, user: 'User') -> bool:
        """Отменить выбор текущего магазина."""
        updated = cls.objects.filter(
            user=user,
            is_current=True
        ).update(
            is_current=False,
            deselected_at=timezone.now()
        )

        return updated > 0


# =============================================================================
# ИНВЕНТАРЬ МАГАЗИНА
# =============================================================================

class StoreInventory(models.Model):
    """
    Инвентарь магазина - все товары на складе магазина.

    БИЗНЕС-ЛОГИКА (ТЗ v2.0):
    1. Товары добавляются при одобрении заказа админом
    2. Все заказы складываются в ОДИН инвентарь
    3. Партнёр может удалить товары из инвентаря при подтверждении
    4. Магазин видит инвентарь только после статуса ACCEPTED
    """

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
        decimal_places=3,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Количество'
    )

    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name='Последнее обновление'
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name='Дата добавления'
    )

    class Meta:
        db_table = 'store_inventory'
        verbose_name = 'Инвентарь магазина'
        verbose_name_plural = 'Инвентарь магазинов'
        unique_together = ['store', 'product']
        ordering = ['-last_updated']
        indexes = [
            models.Index(fields=['store', 'product']),
            models.Index(fields=['store', 'quantity']),
        ]

    def __str__(self) -> str:
        return f"{self.store.name} - {self.product.name}: {self.quantity}"

    @property
    def total_price(self) -> Decimal:
        """Общая стоимость товара в инвентаре."""
        if self.product and self.product.final_price:
            return self.quantity * self.product.final_price
        return Decimal('0')

    @property
    def is_weight_based(self) -> bool:
        """Проверка: весовой ли товар."""
        return self.product.is_weight_based if self.product else False

    def clean(self) -> None:
        """Валидация инвентаря."""
        super().clean()
        if self.quantity < Decimal('0'):
            raise ValidationError({
                'quantity': 'Количество не может быть отрицательным'
            })

    @transaction.atomic
    def add_quantity(self, amount: Decimal) -> None:
        """Добавить количество товара в инвентарь."""
        if amount <= Decimal('0'):
            raise ValidationError('Количество для добавления должно быть больше 0')

        self.quantity += amount
        self.save(update_fields=['quantity', 'last_updated'])

    @transaction.atomic
    def subtract_quantity(self, amount: Decimal) -> None:
        """Вычесть количество товара из инвентаря."""
        if amount <= Decimal('0'):
            raise ValidationError('Количество для вычитания должно быть больше 0')

        if amount > self.quantity:
            raise ValidationError(
                f'Недостаточно товара в инвентаре. '
                f'Доступно: {self.quantity}, запрошено: {amount}'
            )

        self.quantity -= amount
        self.save(update_fields=['quantity', 'last_updated'])

        if self.quantity == Decimal('0'):
            self.delete()
