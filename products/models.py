# apps/products/models.py
"""
Модуль моделей для системы учёта товаров и расходов.

Основные сущности:
- Expense: Расходы (физические/накладные, динамичные/статичные)
- Product: Товары с поддержкой весовых и штучных единиц
- Recipe: Рецепты товаров (связь товар-ингредиент с "котловым" методом)
- ProductCostSnapshot: Кеш себестоимости для быстрого отображения таблицы
- ProductionRecord/ProductionItem: Учёт производства за день

Соответствует ТЗ БайЭл: раздел 4.1 (Учёт расходов и себестоимость)
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

if TYPE_CHECKING:
    from orders.models import StoreOrderItem


# =============================================================================
# КОНСТАНТЫ И CHOICES
# =============================================================================

class ExpenseType(models.TextChoices):
    """Тип расхода: физический (ингредиенты) или накладной (аренда, зарплата)."""
    PHYSICAL = 'physical', 'Физические (ингредиенты)'
    OVERHEAD = 'overhead', 'Накладные (постоянные)'


class AccountingMode(models.TextChoices):
    """
    Режим учёта расхода.

    Соответствует дизайну: экраны "Динамичный учёт" и "Статичный учёт".
    - DYNAMIC: Ингредиенты — расход зависит от объёма производства
    - STATIC: Аренда, свет — фиксированная сумма в месяц
    """
    DYNAMIC = 'dynamic', 'Динамичный (зависит от производства)'
    STATIC = 'static', 'Статичный (фиксированная сумма)'


class ExpenseStatus(models.TextChoices):
    """
    Статус расхода в иерархии Сюзерен/Вассал/Обыватель.

    Из ТЗ:
    - SUZERAIN: Главный ингредиент, от него зависят все расчёты (например, фарш для пельменей)
    - VASSAL: Зависит от Сюзерена, механический учёт
    - CIVILIAN: Базовый расход, зависит от всех статусов
    """
    SUZERAIN = 'suzerain', 'Сюзерен (главный)'
    VASSAL = 'vassal', 'Вассал (зависимый)'
    CIVILIAN = 'civilian', 'Обыватель (базовый)'


class ExpenseState(models.TextChoices):
    """
    Состояние учёта расхода.

    - MECHANICAL: Ручной ввод суммы на экране учёта
    - AUTOMATIC: Автоматический расчёт из пропорций
    """
    MECHANICAL = 'mechanical', 'Механическое (ручной ввод)'
    AUTOMATIC = 'automatic', 'Автоматическое (расчёт)'


class ApplyType(models.TextChoices):
    """Тип применения расхода к товарам."""
    REGULAR = 'regular', 'Обычный (выборочно)'
    UNIVERSAL = 'universal', 'Универсальный (ко всем)'


class ExpenseUnit(models.TextChoices):
    """Единица измерения для физических расходов."""
    PIECE = 'piece', 'Штука'
    KG = 'kg', 'Килограмм'
    GRAM = 'gram', 'Грамм'
    LITER = 'liter', 'Литр'


class ProductUnit(models.TextChoices):
    """Единица измерения товара."""
    PIECE = 'piece', 'Штука'
    KG = 'kg', 'Килограмм'
    LITER = 'liter', 'Литр'
    PACK = 'pack', 'Упаковка'


class DefectStatus(models.TextChoices):
    """Статус бракованного товара."""
    REPORTED = 'reported', 'Сообщено'
    CONFIRMED = 'confirmed', 'Подтверждено'
    REJECTED = 'rejected', 'Отклонено'


# =============================================================================
# БАЗОВЫЕ МИКСИНЫ
# =============================================================================

class TimestampMixin(models.Model):
    """Миксин для автоматических временных меток."""

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Создано'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Обновлено'
    )

    class Meta:
        abstract = True


# =============================================================================
# МОДЕЛЬ: РАСХОДЫ (Expense)
# =============================================================================

class Expense(TimestampMixin):
    """
    Расход (ингредиент или накладной).

    Примеры:
    - Физические (dynamic): мука, фарш, лук, яйца, пакеты
    - Накладные (static): аренда, свет, налог, зарплата уборщицы

    Атрибуты:
        name: Название расхода
        expense_type: Тип (physical/overhead)
        accounting_mode: Режим учёта (dynamic/static) — для разделения экранов
        status: Статус в иерархии (suzerain/vassal/civilian)
        state: Состояние учёта (mechanical/automatic)
        apply_type: Применение к товарам (regular/universal)
    """

    # Основные поля
    name = models.CharField(
        max_length=255,
        verbose_name='Название'
    )
    expense_type = models.CharField(
        max_length=20,
        choices=ExpenseType.choices,
        verbose_name='Тип расхода'
    )
    accounting_mode = models.CharField(
        max_length=20,
        choices=AccountingMode.choices,
        default=AccountingMode.DYNAMIC,
        verbose_name='Режим учёта',
        help_text='Динамичный — для ингредиентов, Статичный — для аренды/зарплаты'
    )

    # Для физических расходов (ингредиентов)
    price_per_unit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена за единицу',
        help_text='Цена за 1 кг/шт/литр ингредиента'
    )
    unit = models.CharField(
        max_length=10,
        choices=ExpenseUnit.choices,
        null=True,
        blank=True,
        verbose_name='Единица измерения'
    )

    # Для накладных расходов
    monthly_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Сумма в месяц',
        help_text='Фиксированная сумма для накладных расходов'
    )

    # Статус и состояние (ТЗ: Сюзерен/Вассал/Обыватель)
    status = models.CharField(
        max_length=20,
        choices=ExpenseStatus.choices,
        default=ExpenseStatus.CIVILIAN,
        verbose_name='Статус'
    )
    state = models.CharField(
        max_length=20,
        choices=ExpenseState.choices,
        default=ExpenseState.AUTOMATIC,
        verbose_name='Состояние учёта'
    )
    apply_type = models.CharField(
        max_length=20,
        choices=ApplyType.choices,
        default=ApplyType.REGULAR,
        verbose_name='Тип применения'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен'
    )

    class Meta:
        db_table = 'expenses'
        verbose_name = 'Расход'
        verbose_name_plural = 'Расходы'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['expense_type', 'is_active']),
            models.Index(fields=['accounting_mode', 'is_active']),
            models.Index(fields=['status']),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_expense_type_display()})"

    def clean(self) -> None:
        """Валидация: проверка обязательных полей в зависимости от типа."""
        super().clean()

        if self.expense_type == ExpenseType.PHYSICAL:
            if not self.price_per_unit:
                raise ValidationError({
                    'price_per_unit': 'Для физических расходов обязательна цена за единицу.'
                })
            if not self.unit:
                raise ValidationError({
                    'unit': 'Для физических расходов обязательна единица измерения.'
                })
            # Физические расходы всегда динамичные
            self.accounting_mode = AccountingMode.DYNAMIC

        elif self.expense_type == ExpenseType.OVERHEAD:
            if not self.monthly_amount and self.state == ExpenseState.AUTOMATIC:
                raise ValidationError({
                    'monthly_amount': 'Для автоматических накладных расходов обязательна месячная сумма.'
                })
            # Накладные расходы по умолчанию статичные
            if self.accounting_mode == AccountingMode.DYNAMIC:
                self.accounting_mode = AccountingMode.STATIC

        # Сюзерен всегда механический (ТЗ)
        if self.status == ExpenseStatus.SUZERAIN:
            self.state = ExpenseState.MECHANICAL

    def save(self, *args, **kwargs) -> None:
        """Сохранение с валидацией."""
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def daily_amount(self) -> Decimal:
        """Дневная сумма для накладных расходов (месяц / 30)."""
        if self.monthly_amount:
            return (self.monthly_amount / Decimal('30')).quantize(Decimal('0.01'))
        return Decimal('0')

    @property
    def is_ingredient(self) -> bool:
        """Является ли расход ингредиентом."""
        return self.expense_type == ExpenseType.PHYSICAL

    @property
    def is_overhead(self) -> bool:
        """Является ли расход накладным."""
        return self.expense_type == ExpenseType.OVERHEAD


# =============================================================================
# МОДЕЛЬ: ТОВАР (Product)
# =============================================================================

class Product(TimestampMixin):
    """
    Товар в каталоге.

    Поддерживает:
    - Штучные товары (пельмени, котлеты)
    - Весовые товары (курица, фарш) — минимум 1 кг, шаг 0.1 кг
    - Автоматический расчёт цены с наценкой

    Ценообразование (ТЗ):
    - base_price: Базовая цена, установленная админом
    - cost_price: Себестоимость (рассчитывается из расходов)
    - markup_percentage: Процент наценки
    - final_price: Итоговая цена = cost_price * (1 + markup/100)

    Роли видят разные цены:
    - Админ: cost_price (себестоимость)
    - Партнёр/Магазин: final_price (с наценкой)
    """

    # Основная информация
    name = models.CharField(
        max_length=200,
        verbose_name='Название'
    )
    description = models.TextField(
        blank=True,
        verbose_name='Описание'
    )

    # Тип товара
    is_weight_based = models.BooleanField(
        default=False,
        verbose_name='Весовой товар',
        help_text='Продаётся на вес с шагом 0.1 кг (минимум 1 кг, если остаток >= 1 кг)'
    )
    unit = models.CharField(
        max_length=10,
        choices=ProductUnit.choices,
        default=ProductUnit.PIECE,
        verbose_name='Единица измерения'
    )

    # Ценообразование
    base_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Базовая цена',
        help_text='Цена, установленная администратором'
    )
    cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Себестоимость',
        help_text='Рассчитывается автоматически из расходов'
    )
    markup_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Наценка (%)',
        help_text='Процент наценки к себестоимости'
    )
    final_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Итоговая цена',
        help_text='Цена с наценкой для партнёров и магазинов'
    )

    # Для весовых товаров
    price_per_100g = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена за 100г',
        help_text='Автоматически рассчитывается для весовых товаров'
    )

    # Склад
    stock_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Количество на складе'
    )

    # Статусы
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен'
    )
    is_available = models.BooleanField(
        default=True,
        verbose_name='Доступен для заказа'
    )

    # Медиа
    image = models.ImageField(
        upload_to='products/',
        null=True,
        blank=True,
        verbose_name='Главное изображение'
    )

    # Коэффициент популярности для "умной наценки" (ТЗ 4.1.4)
    popularity_weight = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal('1.000000'),
        validators=[MinValueValidator(Decimal('0.0001'))],
        verbose_name='Коэффициент популярности',
        help_text='Чем выше — тем больше накладных расходов несёт товар'
    )

    # Deprecated: оставлено для обратной совместимости, использовать final_price
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена (deprecated)',
        help_text='Устаревшее поле, использовать final_price'
    )

    class Meta:
        db_table = 'products'
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active', 'is_available']),
            models.Index(fields=['is_weight_based']),
            models.Index(fields=['name']),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        """Валидация товара."""
        super().clean()

        # Весовые товары должны быть в кг
        if self.is_weight_based and self.unit != ProductUnit.KG:
            raise ValidationError({
                'unit': 'Весовые товары должны иметь единицу измерения "Килограмм".'
            })

        # Нельзя сменить весовой на штучный (ТЗ)
        if self.pk:
            old_instance = Product.objects.filter(pk=self.pk).first()
            if old_instance and old_instance.is_weight_based and not self.is_weight_based:
                raise ValidationError({
                    'is_weight_based': 'Нельзя изменить весовой товар на штучный.'
                })

    def save(self, *args, **kwargs) -> None:
        """Сохранение с пересчётом цен."""
        self.full_clean()
        self._recalculate_prices()
        super().save(*args, **kwargs)

    def _recalculate_prices(self) -> None:
        """Пересчёт итоговой цены и цены за 100г."""
        # Итоговая цена = себестоимость * (1 + наценка/100)
        if self.cost_price > 0 and self.markup_percentage > 0:
            multiplier = Decimal('1') + (self.markup_percentage / Decimal('100'))
            self.final_price = (self.cost_price * multiplier).quantize(Decimal('0.01'))
        elif self.cost_price > 0:
            self.final_price = self.cost_price
        else:
            self.final_price = self.base_price

        # Синхронизация с deprecated полем
        self.price = self.final_price

        # Цена за 100г для весовых товаров
        if self.is_weight_based and self.final_price > 0:
            self.price_per_100g = (self.final_price / Decimal('10')).quantize(Decimal('0.01'))

    def apply_markup(self, markup_percentage: Decimal) -> None:
        """
        Применить наценку к товару.

        Args:
            markup_percentage: Процент наценки (например, 20 для 20%)
        """
        self.markup_percentage = markup_percentage
        self._recalculate_prices()
        self.save(update_fields=['markup_percentage', 'final_price', 'price', 'price_per_100g'])

    def update_cost_price(self, new_cost: Decimal) -> None:
        """
        Обновить себестоимость и пересчитать итоговую цену.

        Args:
            new_cost: Новая себестоимость
        """
        self.cost_price = new_cost
        self._recalculate_prices()
        self.save(update_fields=['cost_price', 'final_price', 'price', 'price_per_100g'])

    def get_price_for_role(self, role: str) -> Decimal:
        """
        Получить цену в зависимости от роли пользователя.

        Args:
            role: Роль пользователя ('admin', 'partner', 'store')

        Returns:
            Себестоимость для админа, итоговая цена для остальных
        """
        if role == 'admin':
            return self.cost_price
        return self.final_price

    def get_minimum_order_quantity(self) -> Decimal:
        """
        Получить минимальное количество для заказа.

        Для весовых товаров:
        - Если остаток >= 1 кг → минимум 1 кг
        - Если остаток < 1 кг → минимум 0.1 кг (ТЗ)
        """
        if not self.is_weight_based:
            return Decimal('1')

        if self.stock_quantity >= Decimal('1'):
            return Decimal('1')
        return Decimal('0.1')

    def get_order_step(self) -> Decimal:
        """Шаг заказа: 0.1 кг для весовых, 1 для штучных."""
        return Decimal('0.1') if self.is_weight_based else Decimal('1')

    def update_popularity_weight(self) -> None:
        """
        Обновить коэффициент популярности на основе продаж за 90 дней.

        Формула: 1.0 + (продано за 90 дней / 1000), максимум 10.0
        Вызывать через Celery beat ежедневно.
        """
        from orders.models import StoreOrderItem

        ninety_days_ago = timezone.now() - timezone.timedelta(days=90)

        sales_qty: Decimal = (
            StoreOrderItem.objects
            .filter(
                product=self,
                order__status='completed',
                order__created_at__gte=ninety_days_ago,
                is_bonus=False
            )
            .aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']
        )

        weight = Decimal('1.0') + (sales_qty / Decimal('1000'))
        weight = min(weight, Decimal('10.0'))

        self.popularity_weight = weight.quantize(Decimal('0.000001'))
        self.save(update_fields=['popularity_weight', 'updated_at'])


# =============================================================================
# МОДЕЛЬ: ИЗОБРАЖЕНИЯ ТОВАРА (ProductImage)
# =============================================================================

class ProductImage(TimestampMixin):
    """Дополнительные изображения товара (до 3 штук)."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Товар'
    )
    image = models.ImageField(
        upload_to='products/',
        verbose_name='Изображение'
    )
    position = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Порядок отображения'
    )

    class Meta:
        db_table = 'product_images'
        verbose_name = 'Изображение товара'
        verbose_name_plural = 'Изображения товаров'
        ordering = ['position']

    def __str__(self) -> str:
        return f"Изображение {self.position} для {self.product.name}"


# =============================================================================
# МОДЕЛЬ: РЕЦЕПТ (Recipe) — связь товара с ингредиентами
# =============================================================================

class Recipe(TimestampMixin):
    """
    Рецепт товара: связь с ингредиентами через "котловой" метод.

    Решает проблему "котлового метода":
    Вместо ввода пропорции 0.01 (50 кг / 5000 шт), пользователь вводит:
    - ingredient_amount: 50 кг муки
    - output_quantity: 5000 булочек
    - proportion: автоматически = 50 / 5000 = 0.01

    Пример использования:
        recipe = Recipe.objects.create(
            product=pelmeni,
            expense=farsh,
            ingredient_amount=Decimal('2'),  # 2 кг фарша
            output_quantity=Decimal('200'),  # на 200 пельменей
        )
        # recipe.proportion == 0.01 (автоматически)
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='recipes',
        verbose_name='Товар'
    )
    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='recipes',
        limit_choices_to={'expense_type': ExpenseType.PHYSICAL},
        verbose_name='Ингредиент'
    )

    # "Котловой" метод: ввод удобных значений
    ingredient_amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество ингредиента',
        help_text='Сколько ингредиента уходит (например, 50 кг муки)'
    )
    output_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество продукции',
        help_text='На какое количество товара (например, 5000 булочек)'
    )

    # Автоматически вычисляемая пропорция
    proportion = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=Decimal('0'),
        verbose_name='Пропорция на единицу',
        help_text='Автоматически: ingredient_amount / output_quantity',
        editable=False
    )

    class Meta:
        db_table = 'product_recipes'
        verbose_name = 'Рецепт'
        verbose_name_plural = 'Рецепты'
        unique_together = [['product', 'expense']]
        indexes = [
            models.Index(fields=['product']),
            models.Index(fields=['expense']),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} ← {self.expense.name}: {self.proportion}"

    def clean(self) -> None:
        """Валидация рецепта."""
        super().clean()

        if self.expense and not self.expense.is_ingredient:
            raise ValidationError({
                'expense': 'Можно привязывать только физические расходы (ингредиенты).'
            })

        if self.output_quantity <= 0:
            raise ValidationError({
                'output_quantity': 'Количество продукции должно быть больше 0.'
            })

    def save(self, *args, **kwargs) -> None:
        """Сохранение с автоматическим расчётом пропорции."""
        self.full_clean()
        self._calculate_proportion()
        super().save(*args, **kwargs)

    def _calculate_proportion(self) -> None:
        """Расчёт пропорции: сколько ингредиента на 1 единицу товара."""
        if self.output_quantity > 0:
            self.proportion = (
                    self.ingredient_amount / self.output_quantity
            ).quantize(Decimal('0.000001'))
        else:
            self.proportion = Decimal('0')

    def get_ingredient_cost_per_unit(self) -> Decimal:
        """
        Стоимость ингредиента на 1 единицу товара.

        Returns:
            proportion * price_per_unit ингредиента
        """
        if self.expense.price_per_unit:
            return (self.proportion * self.expense.price_per_unit).quantize(Decimal('0.01'))
        return Decimal('0')

    def get_ingredient_cost_for_quantity(self, quantity: Decimal) -> Decimal:
        """
        Стоимость ингредиента для заданного количества товара.

        Args:
            quantity: Количество товара

        Returns:
            Стоимость ингредиента
        """
        return (self.get_ingredient_cost_per_unit() * quantity).quantize(Decimal('0.01'))


# =============================================================================
# МОДЕЛЬ: СВЯЗЬ ТОВАРА С РАСХОДАМИ (Legacy, для обратной совместимости)
# =============================================================================

class ProductExpenseRelation(TimestampMixin):
    """
    Связь товара с расходами (устаревшая модель).

    DEPRECATED: Использовать Recipe для ингредиентов.
    Оставлена для обратной совместимости с существующими данными.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='expense_relations',
        verbose_name='Товар'
    )
    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='product_relations',
        verbose_name='Расход'
    )
    proportion = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=Decimal('0'),
        verbose_name='Пропорция'
    )

    class Meta:
        db_table = 'product_expense_relations'
        verbose_name = 'Связь товара с расходом (legacy)'
        verbose_name_plural = 'Связи товаров с расходами (legacy)'
        unique_together = [['product', 'expense']]

    def __str__(self) -> str:
        return f"{self.product} ← {self.expense}"


# =============================================================================
# МОДЕЛЬ: КЕШ СЕБЕСТОИМОСТИ (ProductCostSnapshot)
# =============================================================================

class ProductCostSnapshot(models.Model):
    """
    Кеш себестоимости товара для быстрого отображения таблицы.

    Соответствует экрану "Динамичный учёт" → Секция "Товары":
    | Название | Наценка | Себ-сть | Расход | Доход |

    Обновляется:
    - При изменении рецептов товара
    - При изменении цен ингредиентов
    - При ежедневном пересчёте (Celery task)
    """

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='cost_snapshot',
        verbose_name='Товар'
    )

    # Кешированные значения для таблицы
    cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Себестоимость'
    )
    markup_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Наценка (сумма)'
    )
    ingredient_expense = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Расход на ингредиенты'
    )
    overhead_expense = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Накладные расходы'
    )
    total_expense = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Общий расход'
    )
    revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Доход'
    )
    profit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Прибыль'
    )

    # Метаданные
    last_calculated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Последний расчёт'
    )
    is_outdated = models.BooleanField(
        default=True,
        verbose_name='Требует пересчёта'
    )

    class Meta:
        db_table = 'product_cost_snapshots'
        verbose_name = 'Кеш себестоимости'
        verbose_name_plural = 'Кеши себестоимости'
        indexes = [
            models.Index(fields=['is_outdated']),
        ]

    def __str__(self) -> str:
        return f"Snapshot: {self.product.name}"

    def mark_outdated(self) -> None:
        """Пометить как требующий пересчёта."""
        self.is_outdated = True
        self.save(update_fields=['is_outdated'])

    def recalculate(self) -> None:
        """
        Пересчитать все значения на основе рецептов и расходов.

        Вызывается из CostCalculator.update_product_snapshot().
        """
        from .services import CostCalculator
        CostCalculator.update_product_snapshot(self.product)


# =============================================================================
# МОДЕЛЬ: ЗАПИСЬ ПРОИЗВОДСТВА (ProductionRecord)
# =============================================================================

class ProductionRecord(TimestampMixin):
    """
    Учётная запись производства за день.

    Группирует все произведённые товары и расходы за один день.
    """

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='production_records',
        verbose_name='Партнёр',
        limit_choices_to={'role': 'partner'}
    )
    date = models.DateField(
        verbose_name='Дата производства'
    )

    class Meta:
        db_table = 'production_records'
        verbose_name = 'Запись производства'
        verbose_name_plural = 'Записи производства'
        ordering = ['-date']
        unique_together = [['partner', 'date']]
        indexes = [
            models.Index(fields=['partner', 'date']),
        ]

    def __str__(self) -> str:
        return f"Производство {self.date} ({self.partner})"

    def get_total_quantity(self) -> Decimal:
        """Общее количество произведённой продукции."""
        return self.items.aggregate(
            total=Coalesce(Sum('quantity_produced'), Decimal('0'))
        )['total']

    def get_total_cost(self) -> Decimal:
        """Общая себестоимость за день."""
        return self.items.aggregate(
            total=Coalesce(Sum('total_cost'), Decimal('0'))
        )['total']

    def get_total_revenue(self) -> Decimal:
        """Общая выручка за день."""
        return self.items.aggregate(
            total=Coalesce(Sum('revenue'), Decimal('0'))
        )['total']

    def get_net_profit(self) -> Decimal:
        """Чистая прибыль за день."""
        return self.get_total_revenue() - self.get_total_cost()


# =============================================================================
# МОДЕЛЬ: ПОЗИЦИЯ ПРОИЗВОДСТВА (ProductionItem)
# =============================================================================

class ProductionItem(TimestampMixin):
    """
    Позиция в производственной записи.

    Хранит информацию о произведённом товаре:
    - Количество (или расчёт из Сюзерена)
    - Себестоимость ингредиентов
    - Накладные расходы
    - Выручка и прибыль
    """

    record = models.ForeignKey(
        ProductionRecord,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Запись производства'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='production_items',
        verbose_name='Товар'
    )

    # Ввод количества
    quantity_produced = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Количество произведённого'
    )
    suzerain_amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Количество Сюзерена',
        help_text='Если указано, количество товара рассчитывается автоматически'
    )

    # Расчётные поля
    ingredient_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Стоимость ингредиентов'
    )
    overhead_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Накладные расходы'
    )
    total_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Общая себестоимость'
    )
    cost_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Себестоимость единицы'
    )
    revenue = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Выручка'
    )
    net_profit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Чистая прибыль'
    )

    class Meta:
        db_table = 'production_items'
        verbose_name = 'Позиция производства'
        verbose_name_plural = 'Позиции производства'
        unique_together = [['record', 'product']]
        indexes = [
            models.Index(fields=['record', 'product']),
        ]

    def __str__(self) -> str:
        return f"{self.product.name}: {self.quantity_produced}"


# =============================================================================
# МОДЕЛЬ: МЕХАНИЧЕСКИЙ УЧЁТ РАСХОДОВ (MechanicalExpenseEntry)
# =============================================================================

class MechanicalExpenseEntry(TimestampMixin):
    """
    Запись механического учёта расходов.

    Используется для расходов с state='mechanical' (ручной ввод):
    - Солярка (фактически потрачено сегодня)
    - Обеды курьеров
    - Прочие переменные расходы
    """

    record = models.ForeignKey(
        ProductionRecord,
        on_delete=models.CASCADE,
        related_name='mechanical_entries',
        verbose_name='Запись производства'
    )
    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='mechanical_entries',
        limit_choices_to={'state': ExpenseState.MECHANICAL},
        verbose_name='Расход'
    )
    amount_spent = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Потрачено'
    )
    comment = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Комментарий'
    )

    class Meta:
        db_table = 'mechanical_expense_entries'
        verbose_name = 'Запись механического учёта'
        verbose_name_plural = 'Записи механического учёта'
        unique_together = [['record', 'expense']]

    def __str__(self) -> str:
        return f"{self.expense.name}: {self.amount_spent}"


# =============================================================================
# МОДЕЛИ: БОНУСНАЯ СИСТЕМА
# =============================================================================

class StoreProductCounter(TimestampMixin):
    """
    Счётчик товаров для бонусной системы.

    Каждый 21-й товар — бесплатный (ТЗ).
    Весовые товары НЕ участвуют в бонусах.
    """

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='product_counters',
        verbose_name='Магазин'
    )
    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='store_counters',
        verbose_name='Партнёр',
        limit_choices_to={'role': 'partner'}
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='store_counters',
        verbose_name='Товар'
    )

    total_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Всего куплено'
    )
    bonuses_given = models.PositiveIntegerField(
        default=0,
        verbose_name='Выдано бонусов'
    )
    last_bonus_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Последний бонус'
    )

    class Meta:
        db_table = 'store_product_counters'
        verbose_name = 'Счётчик товаров'
        verbose_name_plural = 'Счётчики товаров'
        unique_together = [['store', 'partner', 'product']]
        indexes = [
            models.Index(fields=['store', 'partner']),
        ]

    def __str__(self) -> str:
        return f"{self.store} - {self.product}: {self.total_count}"

    def get_pending_bonus_count(self) -> int:
        """
        Количество доступных, но не выданных бонусов.

        Формула: (total_count // 21) - bonuses_given
        """
        earned = self.total_count // 21
        return max(0, earned - self.bonuses_given)

    def has_pending_bonus(self) -> bool:
        """Есть ли невыданный бонус."""
        return self.get_pending_bonus_count() > 0


class BonusHistory(TimestampMixin):
    """История начисления бонусов."""

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='bonus_history',
        verbose_name='Магазин'
    )
    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bonus_history',
        verbose_name='Партнёр',
        limit_choices_to={'role': 'partner'}
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='bonus_history',
        verbose_name='Товар'
    )
    order = models.ForeignKey(
        'orders.StoreOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bonuses',
        verbose_name='Заказ'
    )

    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name='Количество бонусных единиц'
    )
    bonus_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Стоимость бонуса'
    )

    class Meta:
        db_table = 'bonus_history'
        verbose_name = 'История бонусов'
        verbose_name_plural = 'История бонусов'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Бонус: {self.product.name} x{self.quantity}"


# =============================================================================
# МОДЕЛЬ: БРАКОВАННЫЕ ТОВАРЫ (DefectiveProduct)
# =============================================================================

class DefectiveProduct(TimestampMixin):
    """Бракованные товары с возможностью возврата."""

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='defective_products',
        verbose_name='Партнёр',
        limit_choices_to={'role': 'partner'}
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='defects',
        verbose_name='Товар'
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Количество'
    )
    reason = models.TextField(
        verbose_name='Причина брака'
    )
    status = models.CharField(
        max_length=20,
        choices=DefectStatus.choices,
        default=DefectStatus.REPORTED,
        verbose_name='Статус'
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата решения'
    )

    class Meta:
        db_table = 'defective_products'
        verbose_name = 'Бракованный товар'
        verbose_name_plural = 'Бракованные товары'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['partner', 'status']),
        ]

    def __str__(self) -> str:
        return f"Брак: {self.product.name} x{self.quantity}"

    def confirm(self) -> None:
        """Подтвердить брак."""
        self.status = DefectStatus.CONFIRMED
        self.resolved_at = timezone.now()
        self.save(update_fields=['status', 'resolved_at'])

    def reject(self) -> None:
        """Отклонить заявку о браке."""
        self.status = DefectStatus.REJECTED
        self.resolved_at = timezone.now()
        self.save(update_fields=['status', 'resolved_at'])
