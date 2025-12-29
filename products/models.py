# apps/products/models.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.1
"""
Модели для управления товарами, расходами и расходами партнёров.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.1:
1. Добавлен ExpenseUnitType - тип учёта расхода (По шт / По весу)
2. Добавлен Product.manual_price - ручная цена от админа
3. Обновлена логика save() - приоритет ручной цены
"""

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


# =============================================================================
# РАСХОДЫ АДМИНА (ПРОИЗВОДСТВЕННЫЕ)
# =============================================================================

class ExpenseType(models.TextChoices):
    """Тип расхода."""
    PHYSICAL = 'physical', 'Физические'
    OVERHEAD = 'overhead', 'Накладные'


class ExpenseStatus(models.TextChoices):
    """Статус расхода в иерархии."""
    SUZERAIN = 'suzerain', 'Сюзерен'
    VASSAL = 'vassal', 'Вассал'
    CIVILIAN = 'civilian', 'Обыватель'


class ExpenseState(models.TextChoices):
    """Состояние учёта."""
    MECHANICAL = 'mechanical', 'Механическое'
    AUTOMATIC = 'automatic', 'Автоматическое'


class ApplyType(models.TextChoices):
    """Тип применения."""
    REGULAR = 'regular', 'Обычный'
    UNIVERSAL = 'universal', 'Универсальный'


# ✅ НОВОЕ v2.1: Тип учёта расхода
class ExpenseUnitType(models.TextChoices):
    """Тип учёта расхода (По шт / По весу)."""
    PER_PIECE = 'per_piece', 'По штукам'
    PER_WEIGHT = 'per_weight', 'По весу (кг)'


class Expense(models.Model):
    """
    Расход на производство (управляется админом).

    Это расходы на производство: ингредиенты, аренда, зарплата и т.д.
    НЕ путать с PartnerExpense (расходы партнёра).

    ИЕРАРХИЯ:
    - Сюзерен: главный ингредиент, от его количества зависят Вассалы
    - Вассал: автоматически зависит от Сюзерена
    - Обыватель: независимый расход
    """

    name = models.CharField(
        max_length=200,
        verbose_name='Название'
    )

    expense_type = models.CharField(
        max_length=10,
        choices=ExpenseType.choices,
        verbose_name='Тип'
    )

    expense_status = models.CharField(
        max_length=10,
        choices=ExpenseStatus.choices,
        default=ExpenseStatus.CIVILIAN,
        verbose_name='Статус в иерархии'
    )

    expense_state = models.CharField(
        max_length=15,
        choices=ExpenseState.choices,
        default=ExpenseState.AUTOMATIC,
        verbose_name='Состояние учёта'
    )

    apply_type = models.CharField(
        max_length=10,
        choices=ApplyType.choices,
        default=ApplyType.REGULAR,
        verbose_name='Тип применения',
        help_text='Универсальный = применяется ко всем товарам (свет, аренда)'
    )

    # ✅ НОВОЕ v2.1: Тип учёта (По шт / По весу)
    unit_type = models.CharField(
        max_length=15,
        choices=ExpenseUnitType.choices,
        default=ExpenseUnitType.PER_PIECE,
        verbose_name='Тип учёта',
        help_text='По штукам или по весу (кг)'
    )

    # Зависимость Вассала от Сюзерена
    depends_on_suzerain = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vassals',
        limit_choices_to={'expense_status': 'suzerain'},
        verbose_name='Зависит от Сюзерена',
        help_text='Только для Вассалов: от какого Сюзерена зависит количество'
    )

    dependency_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Коэффициент зависимости',
        help_text='Только для Вассалов: какая пропорция от Сюзерена (например: 0.095)'
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Количество',
        help_text='Для Сюзеренов - вводится вручную, для Вассалов - рассчитывается'
    )

    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена за единицу',
        help_text='Цена за штуку или за кг (в зависимости от unit_type)'
    )

    monthly_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Месячная сумма',
        help_text='Например: Аренда 35,000 сом/месяц'
    )

    daily_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Дневная сумма',
        help_text='Например: Фарш 28,350 сом/день'
    )

    description = models.TextField(blank=True, verbose_name='Описание')
    is_active = models.BooleanField(default=True, verbose_name='Активен')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expenses'
        verbose_name = 'Расход (производство)'
        verbose_name_plural = 'Расходы (производство)'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['expense_type']),
            models.Index(fields=['expense_status']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_expense_type_display()})"

    def clean(self):
        """Валидация расхода с учётом иерархии."""
        super().clean()

        # Правило 1: Только Вассалы могут зависеть от Сюзеренов
        if self.depends_on_suzerain and self.expense_status != ExpenseStatus.VASSAL:
            raise ValidationError({
                'depends_on_suzerain':
                    'Только расходы со статусом "Вассал" могут зависеть от Сюзерена'
            })

        # Правило 2: Вассал ДОЛЖЕН иметь Сюзерена
        if self.expense_status == ExpenseStatus.VASSAL and not self.depends_on_suzerain:
            raise ValidationError({
                'depends_on_suzerain':
                    'Вассал должен зависеть от Сюзерена. Выберите Сюзерена или измените статус.'
            })

        # Правило 3: Вассал ДОЛЖЕН иметь коэффициент
        if self.expense_status == ExpenseStatus.VASSAL and not self.dependency_ratio:
            raise ValidationError({
                'dependency_ratio':
                    'Укажите коэффициент зависимости (например: 0.095 для 9.5%)'
            })

    def calculate_vassal_quantity(self) -> Decimal:
        """Рассчитать количество для Вассала."""
        if self.expense_status != ExpenseStatus.VASSAL:
            return self.quantity

        if not self.depends_on_suzerain or not self.dependency_ratio:
            return Decimal('0')

        suzerain_quantity = self.depends_on_suzerain.quantity
        calculated = suzerain_quantity * self.dependency_ratio

        return calculated.quantize(Decimal('0.001'))

    def calculate_amount(self) -> Decimal:
        """Рассчитать сумму расхода."""
        if self.expense_status == ExpenseStatus.VASSAL:
            vassal_quantity = self.calculate_vassal_quantity()
            amount = vassal_quantity * self.unit_cost
            return amount.quantize(Decimal('0.01'))

        return self.daily_amount or self.monthly_amount or Decimal('0')

    def save(self, *args, **kwargs):
        """Автоматический расчёт при сохранении."""
        if (self.expense_status == ExpenseStatus.VASSAL and
                self.expense_state == ExpenseState.AUTOMATIC):
            self.quantity = self.calculate_vassal_quantity()

        super().save(*args, **kwargs)


# =============================================================================
# РАСХОДЫ ПАРТНЁРА (v2.0)
# =============================================================================

class PartnerExpense(models.Model):
    """
    Расход партнёра (ТЗ v2.0).

    ТЗ: "Партнер будет добавлять расходы. Для этого нужны поля:
    1. Amount - сумма расхода
    2. Description - описание расхода"

    Расходы партнёра влияют на статистику админа.
    """

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'partner'},
        related_name='partner_expenses',
        verbose_name='Партнёр'
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name='Сумма расхода',
        help_text='Сумма расхода в сомах'
    )

    description = models.TextField(
        verbose_name='Описание расхода',
        help_text='Причина/описание расхода'
    )

    date = models.DateField(
        default=timezone.now,
        verbose_name='Дата расхода',
        db_index=True
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
        db_table = 'partner_expenses'
        verbose_name = 'Расход партнёра'
        verbose_name_plural = 'Расходы партнёров'
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['partner', '-date']),
            models.Index(fields=['date']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.partner.get_full_name()}: {self.amount} сом - {self.description[:50]}"

    def clean(self):
        """Валидация расхода."""
        super().clean()

        if self.amount <= Decimal('0'):
            raise ValidationError({
                'amount': 'Сумма расхода должна быть больше 0'
            })

        if not self.description or not self.description.strip():
            raise ValidationError({
                'description': 'Описание расхода обязательно'
            })


# =============================================================================
# ТОВАР
# =============================================================================

class ProductUnit(models.TextChoices):
    PIECE = 'piece', 'Штука'
    KG = 'kg', 'Килограмм'
    LITER = 'liter', 'Литр'
    PACK = 'pack', 'Упаковка'


class Product(models.Model):
    """
    Товар в каталоге.

    ВАЖНО (ТЗ v2.1):
    - Создаётся админом
    - Цена: manual_price (ручная) ИЛИ авторасчёт (себестоимость + наценка)
    - Запрещена смена категории "Весовой" → "Штучный"
    - Бонусные товары: только штучные, каждый 21-й бесплатно
    """

    name = models.CharField(
        max_length=200,
        unique=True,
        verbose_name='Название'
    )

    description = models.TextField(
        blank=True,
        verbose_name='Описание',
        help_text='Максимум 250 символов'
    )

    is_weight_based = models.BooleanField(
        default=False,
        verbose_name='Весовой товар'
    )

    unit = models.CharField(
        max_length=10,
        choices=ProductUnit.choices,
        default=ProductUnit.PIECE,
        verbose_name='Единица измерения'
    )

    # =====================================================================
    # ЦЕНООБРАЗОВАНИЕ
    # =====================================================================

    average_cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Себестоимость',
        help_text='Обновляется из производства'
    )

    markup_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('10'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('1000'))],
        verbose_name='Наценка (%)',
        help_text='Устанавливается админом'
    )

    # ✅ НОВОЕ v2.1: Ручная цена от админа
    manual_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Ручная цена',
        help_text='Если установлена, используется вместо автоматического расчёта'
    )

    final_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена продажи',
        help_text='Авторасчёт или manual_price'
    )

    price_per_100g = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Цена за 100г'
    )

    # =====================================================================
    # СКЛАД И СТАТУСЫ
    # =====================================================================

    stock_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='На складе'
    )

    is_active = models.BooleanField(default=True, verbose_name='Активен')
    is_available = models.BooleanField(default=True, verbose_name='Доступен')

    is_bonus = models.BooleanField(
        default=False,
        verbose_name='Бонусный',
        help_text='Каждый 21-й товар бесплатно (только для штучных)'
    )

    popularity_weight = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal('1.000000'),
        validators=[MinValueValidator(Decimal('0.0001'))],
        verbose_name='Коэффициент популярности'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'products'
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active', 'is_available']),
            models.Index(fields=['name']),
            models.Index(fields=['is_bonus']),  # ✅ НОВОЕ v2.1
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        # Валидация описания (250 символов)
        if self.description and len(self.description) > 250:
            raise ValidationError({
                'description': 'Описание не может превышать 250 символов'
            })

        if self.is_weight_based and self.unit != ProductUnit.KG:
            raise ValidationError({
                'unit': 'Весовые товары должны быть в кг'
            })

        # ТЗ: Весовые товары НЕ могут быть бонусными
        if self.is_weight_based and self.is_bonus:
            raise ValidationError({
                'is_bonus': 'Весовые товары не могут быть бонусными'
            })

        # Проверка на смену категории "Весовой" → "Штучный"
        if self.pk:
            old_product = Product.objects.filter(pk=self.pk).first()
            if old_product and old_product.is_weight_based and not self.is_weight_based:
                raise ValidationError({
                    'is_weight_based': 'Запрещена смена категории "Весовой" → "Штучный"'
                })

    def save(self, *args, **kwargs):
        """
        Автоматический расчёт цены.

        ЛОГИКА (v2.1):
        1. Если manual_price установлена → использовать её
        2. Иначе → рассчитать: себестоимость × (1 + наценка%)
        """
        # ✅ НОВОЕ v2.1: Приоритет ручной цены
        if self.manual_price is not None and self.manual_price > 0:
            # Используем ручную цену
            self.final_price = self.manual_price
        elif self.average_cost_price > 0:
            # Автоматический расчёт: себестоимость + наценка
            self.final_price = self.average_cost_price * (
                    Decimal('1') + self.markup_percentage / Decimal('100')
            )

        # Цена за 100г для весовых товаров
        if self.is_weight_based and self.final_price > 0:
            self.price_per_100g = self.final_price / Decimal('10')

        super().save(*args, **kwargs)

    def update_average_cost_price(self):
        """Обновить себестоимость из производства."""
        from django.db.models import Avg

        avg = self.production_batches.aggregate(
            avg_cost=Avg('cost_price_calculated')
        )['avg_cost']

        if avg:
            self.average_cost_price = avg
            self.save()

    @property
    def profit_per_unit(self) -> Decimal:
        """Прибыль с единицы."""
        return self.final_price - self.average_cost_price

    @property
    def effective_price(self) -> Decimal:
        """
        Эффективная цена (для использования в расчётах).

        Приоритет:
        1. manual_price (если установлена)
        2. final_price (авторасчёт)
        """
        if self.manual_price is not None and self.manual_price > 0:
            return self.manual_price
        return self.final_price

    def validate_order_quantity(self, quantity: Decimal):
        """
        Валидация количества для заказа.

        ТЗ v2.0:
        - Весовые: минимум 1 кг (или 0.1 кг если остаток < 1 кг), шаг 0.1 кг
        - Штучные: минимум 1 шт, только целые числа
        """
        if self.is_weight_based:
            min_qty = Decimal('1.0') if self.stock_quantity >= Decimal('1.0') else Decimal('0.1')
            if quantity < min_qty:
                raise ValidationError(f'Минимум: {min_qty} кг')
            if (quantity * Decimal('10')) % Decimal('1') != Decimal('0'):
                raise ValidationError('Шаг: 0.1 кг')
        else:
            if quantity < Decimal('1'):
                raise ValidationError('Минимум: 1 шт')
            if quantity != int(quantity):
                raise ValidationError('Только целые числа')


# =============================================================================
# ПРОИЗВОДСТВО
# =============================================================================

class ProductionBatch(models.Model):
    """Производственная партия (записывает админ)."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='production_batches'
    )

    date = models.DateField(verbose_name='Дата производства')

    quantity_produced = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name='Произведено'
    )

    total_daily_expenses = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Дневные расходы'
    )

    total_monthly_expenses_per_day = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Месячные (на день)'
    )

    cost_price_calculated = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Себестоимость'
    )

    notes = models.TextField(blank=True, verbose_name='Заметки')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'production_batches'
        verbose_name = 'Производственная партия'
        verbose_name_plural = 'Производственные партии'
        ordering = ['-date']
        indexes = [
            models.Index(fields=['product', '-date']),
        ]
        unique_together = ['product', 'date']

    def __str__(self):
        return f"{self.product.name} - {self.date}"

    def calculate_cost_price(self) -> Decimal:
        """
        Рассчитать себестоимость.

        Формула: (дневные + месячные/30) / количество
        """
        if self.quantity_produced <= 0:
            return Decimal('0')

        total = self.total_daily_expenses + self.total_monthly_expenses_per_day
        return (total / self.quantity_produced).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        """Автоматический расчёт."""
        self.cost_price_calculated = self.calculate_cost_price()
        super().save(*args, **kwargs)
        self.product.update_average_cost_price()


# =============================================================================
# ИЗОБРАЖЕНИЯ
# =============================================================================

class ProductImage(models.Model):
    """Изображения товара (до 3 штук)."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images'
    )

    image = models.ImageField(upload_to='products/%Y/%m/')
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'product_images'
        verbose_name = 'Изображение'
        verbose_name_plural = 'Изображения'
        ordering = ['product', 'order']
        unique_together = ['product', 'order']

    def clean(self):
        if not self.pk:
            existing = ProductImage.objects.filter(product=self.product).count()
            if existing >= 3:
                raise ValidationError('Максимум 3 изображения')


# =============================================================================
# СВЯЗЬ ТОВАР-РАСХОД
# =============================================================================

class ProductExpenseRelation(models.Model):
    """
    Связь товара с расходом.

    ТЗ v2.0: Товар выбирает расходы которые к нему применяются.
    Универсальные расходы (свет, аренда) применяются ко всем автоматически.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='expense_relations'
    )

    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='product_relations'
    )

    proportion = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Пропорция расхода для товара (опционально)'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'product_expense_relations'
        verbose_name = 'Связь товар-расход'
        verbose_name_plural = 'Связи товар-расход'
        unique_together = ['product', 'expense']

    def __str__(self):
        return f"{self.product.name} ← {self.expense.name}"