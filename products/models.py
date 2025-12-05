# apps/products/models.py
"""
Модели для управления товарами и расходами.

КРИТИЧЕСКИ ВАЖНО:
- ТОЛЬКО АДМИН управляет всем (товары, расходы, производство)
- Партнёры и магазины ТОЛЬКО читают
- Цена автоматически рассчитывается с наценкой
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


# =============================================================================
# РАСХОДЫ
# =============================================================================

class ExpenseType(models.TextChoices):
    """Тип расхода."""
    PHYSICAL = 'physical', 'Физические'
    OVERHEAD = 'overhead', 'Накладные'


class ExpenseStatus(models.TextChoices):
    """Статус расхода."""
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


class Expense(models.Model):
    """Расход (управляется админом)."""

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
        default=ExpenseStatus.CIVILIAN
    )

    expense_state = models.CharField(
        max_length=15,
        choices=ExpenseState.choices,
        default=ExpenseState.AUTOMATIC
    )

    apply_type = models.CharField(
        max_length=10,
        choices=ApplyType.choices,
        default=ApplyType.REGULAR
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

    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expenses'
        verbose_name = 'Расход'
        verbose_name_plural = 'Расходы'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['expense_type']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_expense_type_display()})"


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

    ВАЖНО:
    - Создаётся админом
    - Цена автоматически: final_price = cost × (1 + markup/100)
    """

    name = models.CharField(
        max_length=200,
        unique=True,
        verbose_name='Название'
    )

    description = models.TextField(
        blank=True,
        max_length=250,
        verbose_name='Описание'
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

    # Ценообразование
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

    final_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Цена продажи',
        help_text='АВТОМАТИЧЕСКИ рассчитывается'
    )

    price_per_100g = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Цена за 100г'
    )

    # Склад
    stock_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='На складе'
    )

    is_active = models.BooleanField(default=True, verbose_name='Активен')
    is_available = models.BooleanField(default=True, verbose_name='Доступен')
    is_bonus = models.BooleanField(default=False, verbose_name='Бонусный')

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
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        if self.is_weight_based and self.unit != ProductUnit.KG:
            raise ValidationError({
                'unit': 'Весовые товары должны быть в кг'
            })

        if self.is_weight_based and self.is_bonus:
            raise ValidationError({
                'is_bonus': 'Весовые товары не могут быть бонусными'
            })

    def save(self, *args, **kwargs):
        """Автоматический расчёт цены."""
        if self.average_cost_price > 0:
            self.final_price = self.average_cost_price * (
                    Decimal('1') + self.markup_percentage / Decimal('100')
            )

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
    def profit_per_unit(self):
        """Прибыль с единицы."""
        return self.final_price - self.average_cost_price

    def validate_order_quantity(self, quantity: Decimal):
        """Валидация количества."""
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

    def calculate_cost_price(self):
        """Рассчитать себестоимость."""
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
    """Связь товара с расходом."""

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
        validators=[MinValueValidator(Decimal('0'))]
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'product_expense_relations'
        unique_together = ['product', 'expense']