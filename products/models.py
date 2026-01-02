# apps/products/models.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v3.0
"""
Модели для управления товарами и расходами.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v3.0 (на основе правильного понимания ТЗ):
1. Убрана модель Ingredient (была ошибкой!)
2. Все расходы (физические и накладные) - это Expense
3. Добавлена модель ProductRecipe для связи товаров с расходами через пропорции
4. ProductionBatch поддерживает ДВА сценария расчёта:
   - От количества товара
   - От объёма Сюзерена
5. Умная наценка (перераспределение накладных по объёму производства)

ТЗ 4.1:
- Физические расходы: лук, мука, фарш, тесто, упаковка
- Накладные расходы: аренда, налоги, зарплата, топливо, вода
- Статусы: Сюзерен, Вассал, Обыватель
- Состояния: Механическое, Автоматическое
- Типы: Обычный, Универсальный
"""

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


# =============================================================================
# ТИПЫ И СТАТУСЫ РАСХОДОВ
# =============================================================================

class ExpenseType(models.TextChoices):
    """
    Тип расхода (ТЗ 4.1.1).

    - PHYSICAL: Физические (лук, мука, фарш, тесто, упаковка)
    - OVERHEAD: Накладные (аренда, налоги, зарплата, топливо, вода)
    """
    PHYSICAL = 'physical', 'Физические'
    OVERHEAD = 'overhead', 'Накладные'


class ExpenseStatus(models.TextChoices):
    """
    Статус расхода в иерархии (ТЗ 4.1.2.1).

    - SUZERAIN: Сюзерен (главный, от него зависят все остальные)
    - VASSAL: Вассал (зависит от Сюзерена, устанавливается автоматически)
    - CIVILIAN: Обыватель (базовый, зависит от всех)
    """
    SUZERAIN = 'suzerain', 'Сюзерен'
    VASSAL = 'vassal', 'Вассал'
    CIVILIAN = 'civilian', 'Обыватель'


class ExpenseState(models.TextChoices):
    """
    Состояние учёта (ТЗ 4.1.2.1).

    - MECHANICAL: Механическое (ручной ввод, статус → Вассал)
    - AUTOMATIC: Автоматическое (зависит от механического)
    """
    MECHANICAL = 'mechanical', 'Механическое'
    AUTOMATIC = 'automatic', 'Автоматическое'


class ApplyType(models.TextChoices):
    """
    Тип применения (ТЗ 4.1.2.1).

    - REGULAR: Обычный (применяется к отдельным товарам вручную)
    - UNIVERSAL: Универсальный (применяется ко всем товарам сразу)
    """
    REGULAR = 'regular', 'Обычный'
    UNIVERSAL = 'universal', 'Универсальный'


class ExpenseUnitType(models.TextChoices):
    """
    Тип учёта расхода (только для физических).

    - PER_PIECE: По штукам
    - PER_WEIGHT: По весу (кг)
    """
    PER_PIECE = 'per_piece', 'По штукам'
    PER_WEIGHT = 'per_weight', 'По весу (кг)'


# =============================================================================
# РАСХОДЫ (ЕДИНАЯ МОДЕЛЬ ДЛЯ ФИЗИЧЕСКИХ И НАКЛАДНЫХ)
# =============================================================================

class Expense(models.Model):
    """
    Расход на производство (ТЗ 4.1).

    ЕДИНАЯ модель для ВСЕХ расходов:
    - Физические (type=physical): Лук, Мука, Фарш, Тесто, Упаковка
    - Накладные (type=overhead): Аренда, Зарплата, Электричество, Вода

    ПРИМЕРЫ:

    Физический расход (Мука):
        name = "Мука"
        expense_type = PHYSICAL
        expense_status = SUZERAIN  # главный ингредиент для теста
        expense_state = MECHANICAL  # ручной ввод количества
        unit_type = PER_WEIGHT
        price_per_unit = 50.00  # 50 сом/кг

    Накладной расход (Аренда):
        name = "Аренда"
        expense_type = OVERHEAD
        expense_status = CIVILIAN
        expense_state = AUTOMATIC
        monthly_amount = 30000.00
        daily_amount = 1000.00  # автоматически 30000/30
    """

    name = models.CharField(
        max_length=200,
        verbose_name='Название',
        help_text='Например: Мука, Фарш, Аренда, Зарплата'
    )

    # Классификация
    expense_type = models.CharField(
        max_length=10,
        choices=ExpenseType.choices,
        verbose_name='Тип',
        help_text='Физические (ингредиенты) или Накладные (операционные)'
    )

    expense_status = models.CharField(
        max_length=10,
        choices=ExpenseStatus.choices,
        default=ExpenseStatus.CIVILIAN,
        verbose_name='Статус в иерархии',
        help_text='Сюзерен (главный), Вассал (зависимый), Обыватель (базовый)'
    )

    expense_state = models.CharField(
        max_length=15,
        choices=ExpenseState.choices,
        default=ExpenseState.AUTOMATIC,
        verbose_name='Состояние учёта',
        help_text='Механическое (ручной ввод) или Автоматическое (расчётное)'
    )

    apply_type = models.CharField(
        max_length=10,
        choices=ApplyType.choices,
        default=ApplyType.REGULAR,
        verbose_name='Тип применения',
        help_text='Обычный (к отдельным товарам) или Универсальный (ко всем)'
    )

    # Для физических расходов
    unit_type = models.CharField(
        max_length=15,
        choices=ExpenseUnitType.choices,
        null=True,
        blank=True,
        verbose_name='Тип учёта',
        help_text='По штукам или По весу (только для физических)'
    )

    price_per_unit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Цена за единицу',
        help_text='Для физических: цена за 1 кг/шт'
    )

    # Зависимости (для Вассалов)
    depends_on_suzerain = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vassals',
        limit_choices_to={'expense_status': ExpenseStatus.SUZERAIN},
        verbose_name='Зависит от Сюзерена'
    )

    dependency_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name='Коэффициент зависимости',
        help_text='Пропорция от Сюзерена (например, 0.5 = 50%)'
    )

    # Суммы (для накладных расходов)
    monthly_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Месячная сумма'
    )

    daily_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Дневная сумма'
    )

    description = models.TextField(
        blank=True,
        verbose_name='Описание'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expenses'
        verbose_name = 'Расход'
        verbose_name_plural = 'Расходы'
        ordering = ['name']
        indexes = [
            models.Index(fields=['expense_type', 'is_active']),
            models.Index(fields=['expense_status']),
        ]

    def __str__(self):
        type_str = 'Физ' if self.expense_type == ExpenseType.PHYSICAL else 'Накл'
        status_str = self.get_expense_status_display()[0]  # С/В/О
        return f"[{type_str}][{status_str}] {self.name}"

    def clean(self):
        """Валидация полей."""
        # Физические должны иметь unit_type и price_per_unit
        if self.expense_type == ExpenseType.PHYSICAL:
            if not self.unit_type:
                raise ValidationError('Физический расход должен иметь тип учёта')
            if not self.price_per_unit or self.price_per_unit <= 0:
                raise ValidationError('Физический расход должен иметь цену за единицу')

        # Вассал должен зависеть от Сюзерена
        if self.expense_status == ExpenseStatus.VASSAL:
            if not self.depends_on_suzerain:
                raise ValidationError('Вассал должен зависеть от Сюзерена')
            if not self.dependency_ratio:
                raise ValidationError('Вассал должен иметь коэффициент зависимости')

    def calculate_amount(self, quantity: Decimal = None) -> Decimal:
        """
        Рассчитать сумму расхода.

        Args:
            quantity: Количество (для физических расходов)

        Returns:
            Сумма расхода
        """
        if self.expense_type == ExpenseType.PHYSICAL and quantity:
            # Физический: quantity × price_per_unit
            return (quantity * (self.price_per_unit or Decimal('0'))).quantize(Decimal('0.01'))
        else:
            # Накладной: daily + monthly/30
            return self.daily_amount + (self.monthly_amount / 30).quantize(Decimal('0.01'))


# =============================================================================
# РАСХОДЫ ПАРТНЁРОВ (для отчётности админа)
# =============================================================================

class PartnerExpense(models.Model):
    """Расходы партнёра (ручной ввод)."""

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='partner_expenses',
        limit_choices_to={'role': 'partner'}
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )

    description = models.CharField(max_length=500)
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'partner_expenses'
        verbose_name = 'Расход партнёра'
        verbose_name_plural = 'Расходы партнёров'
        ordering = ['-date']
        indexes = [
            models.Index(fields=['partner', '-date']),
        ]

    def __str__(self):
        return f"{self.partner.email} - {self.amount} сом ({self.date})"


# =============================================================================
# ТОВАРЫ
# =============================================================================

class ProductUnit(models.TextChoices):
    """Единицы измерения товаров."""
    KG = 'kg', 'Килограмм'
    PIECE = 'piece', 'Штука'
    LITER = 'liter', 'Литр'


class Product(models.Model):
    """Товар в каталоге."""

    name = models.CharField(
        max_length=200,
        unique=True,
        verbose_name='Название'
    )

    description = models.TextField(
        max_length=250,
        blank=True,
        verbose_name='Описание'
    )

    unit = models.CharField(
        max_length=10,
        choices=ProductUnit.choices,
        default=ProductUnit.PIECE,
        verbose_name='Единица измерения'
    )

    is_weight_based = models.BooleanField(
        default=False,
        verbose_name='Весовой товар'
    )

    is_bonus = models.BooleanField(
        default=False,
        verbose_name='Бонусный'
    )

    # Ценообразование
    average_cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Средняя себестоимость'
    )

    markup_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('20'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Наценка (%)'
    )

    manual_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Ручная цена'
    )

    final_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Цена продажи'
    )

    stock_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Количество на складе'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен'
    )

    is_available = models.BooleanField(
        default=True,
        verbose_name='Доступен'
    )

    popularity_weight = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal('1.000000'),
        validators=[MinValueValidator(Decimal('0.0001'))],
        verbose_name='Коэффициент популярности',
        help_text='Для умной наценки (перераспределение накладных)'
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

    @property
    def price_per_100g(self) -> Decimal:
        """Цена за 100 грамм (для весовых)."""
        if self.is_weight_based:
            return (self.final_price / 10).quantize(Decimal('0.01'))
        return Decimal('0')

    @property
    def profit_per_unit(self) -> Decimal:
        """Прибыль с единицы."""
        return self.final_price - self.average_cost_price

    @property
    def effective_price(self) -> Decimal:
        """Эффективная цена (с учётом manual_price)."""
        if self.manual_price is not None and self.manual_price > 0:
            return self.manual_price
        return self.final_price

    def save(self, *args, **kwargs):
        """Автоматический расчёт цены."""
        # Если есть manual_price, используем его
        if self.manual_price and self.manual_price > 0:
            self.final_price = self.manual_price
        else:
            # Автоматический расчёт: себестоимость + наценка
            markup_multiplier = Decimal('1') + (self.markup_percentage / 100)
            self.final_price = (self.average_cost_price * markup_multiplier).quantize(Decimal('0.01'))

        super().save(*args, **kwargs)

    def update_average_cost_price(self):
        """Обновить среднюю себестоимость из ProductionBatch."""
        from django.db.models import Avg

        avg = self.production_batches.aggregate(
            avg_cost=Avg('cost_per_unit')
        )['avg_cost']

        if avg:
            self.average_cost_price = avg
            self.save()


# =============================================================================
# РЕЦЕПТЫ ТОВАРОВ (СВЯЗЬ С РАСХОДАМИ)
# =============================================================================

class ProductRecipe(models.Model):
    """
    Рецепт товара - связь с расходами через пропорции (ТЗ 4.1.3).

    ПРИМЕРЫ:

    Пельмени:
        - Фарш (Сюзерен): quantity_per_unit = 0.01 (10г на 1 пельмень)
        - Лук: proportion = 0.5 (50% от фарша)
        - Тесто: proportion = 1.0 (100% от фарша)
        - Фаршировщик (накладной): proportion = None (распределяется автоматически)

    Тесто:
        - Мука (Сюзерен): quantity_per_unit = 0.5 (500г на 1 кг теста)
        - Вода: proportion = 0.3 (30% от муки)
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='recipe_items',
        verbose_name='Товар'
    )

    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='recipe_usages',
        verbose_name='Расход'
    )

    # Для Сюзерена: количество на 1 единицу товара
    quantity_per_unit = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name='Количество на единицу',
        help_text='Для Сюзерена: кг/шт на 1 единицу товара'
    )

    # Для остальных: пропорция от Сюзерена
    proportion = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Пропорция',
        help_text='Пропорция от Сюзерена (например, 0.5 = 50%)'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'product_recipes'
        verbose_name = 'Рецепт товара'
        verbose_name_plural = 'Рецепты товаров'
        unique_together = [['product', 'expense']]
        indexes = [
            models.Index(fields=['product', 'expense']),
        ]

    def __str__(self):
        if self.quantity_per_unit:
            return f"{self.product.name}: {self.expense.name} (Сюзерен, {self.quantity_per_unit}/шт)"
        elif self.proportion:
            return f"{self.product.name}: {self.expense.name} (пропорция {self.proportion})"
        else:
            return f"{self.product.name}: {self.expense.name}"

    def clean(self):
        """Валидация."""
        # Сюзерен должен иметь quantity_per_unit
        if self.expense.expense_status == ExpenseStatus.SUZERAIN:
            if not self.quantity_per_unit:
                raise ValidationError('Сюзерен должен иметь quantity_per_unit')
        else:
            # Остальные должны иметь proportion (кроме универсальных)
            if self.expense.apply_type != ApplyType.UNIVERSAL and not self.proportion:
                raise ValidationError('Расход должен иметь пропорцию')


# =============================================================================
# ПРОИЗВОДСТВЕННЫЕ ПАРТИИ
# =============================================================================

class ProductionBatch(models.Model):
    """
    Производственная партия (ТЗ 4.1.3).

    ДВА СЦЕНАРИЯ РАСЧЁТА:
    1. Ввод количества товара → расчёт расходов
    2. Ввод объёма Сюзерена → расчёт количества товара

    ПРИМЕР (Пельмени, 200 шт):

    Сценарий 1: Ввели 200 пельменей
        - Фарш (Сюзерен): 200 × 0.01 = 2 кг
        - Лук (50%): 2 × 0.5 = 1 кг
        - Тесто (100%): 2 × 1.0 = 2 кг
        - Фаршировщик: распределяется пропорционально

    Сценарий 2: Ввели 2 кг фарша
        - Количество: 2 / 0.01 = 200 пельменей
        - Остальное аналогично
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='production_batches',
        verbose_name='Товар'
    )

    date = models.DateField(verbose_name='Дата производства')

    # Результат расчёта
    quantity_produced = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name='Произведено'
    )

    # Расходы (детализация)
    total_physical_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Физические расходы'
    )

    total_overhead_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Накладные расходы'
    )

    cost_per_unit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Себестоимость за единицу'
    )

    # Метаданные
    input_type = models.CharField(
        max_length=20,
        choices=[
            ('quantity', 'От количества товара'),
            ('suzerain', 'От объёма Сюзерена')
        ],
        default='quantity',
        verbose_name='Тип ввода'
    )

    notes = models.TextField(blank=True, verbose_name='Заметки')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'production_batches'
        verbose_name = 'Производственная партия'
        verbose_name_plural = 'Производственные партии'
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['product', '-date']),
            models.Index(fields=['-date']),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.date} ({self.quantity_produced} шт)"

    def calculate_cost_per_unit(self) -> Decimal:
        """Рассчитать себестоимость за единицу."""
        if self.quantity_produced <= 0:
            return Decimal('0')

        total = self.total_physical_cost + self.total_overhead_cost
        return (total / self.quantity_produced).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        """Автоматический расчёт себестоимости."""
        self.cost_per_unit = self.calculate_cost_per_unit()
        super().save(*args, **kwargs)

        # Обновляем среднюю себестоимость товара
        if hasattr(self.product, 'update_average_cost_price'):
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
        unique_together = [['product', 'order']]

    def clean(self):
        if not self.pk:
            existing = ProductImage.objects.filter(product=self.product).count()
            if existing >= 3:
                raise ValidationError('Максимум 3 изображения')


# =============================================================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ (для существующих эндпоинтов)
# =============================================================================

class ProductExpenseRelation(models.Model):
    """
    УСТАРЕЛО! Используйте ProductRecipe вместо этой модели.

    Оставлено для обратной совместимости с существующими эндпоинтами.
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
        validators=[MinValueValidator(Decimal('0'))]
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'product_expense_relations'
        verbose_name = 'Связь товар-расход (устарело)'
        verbose_name_plural = 'Связи товар-расход (устарело)'
        unique_together = [['product', 'expense']]

    def __str__(self):
        return f"{self.product.name} ← {self.expense.name}"