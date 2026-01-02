# apps/products/services.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v3.0
"""
Сервисы для расчёта производства и умной наценки.

КРИТИЧЕСКИЕ КОМПОНЕНТЫ v3.0:
1. ProductionCalculator - расчёт по двум сценариям (количество/Сюзерен)
2. OverheadDistributor - умная наценка (перераспределение по объёму)
3. ExpenseService - работа с иерархией расходов (Сюзерен/Вассал/Обыватель)
"""

from decimal import Decimal
from datetime import date
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from django.db import transaction
from django.db.models import Sum, Q

from .models import (
    Expense,
    Product,
    ProductRecipe,
    ProductionBatch,
    ExpenseType,
    ExpenseStatus,
    ExpenseState,
    ApplyType,
)


# =============================================================================
# DATACLASSES ДЛЯ РЕЗУЛЬТАТОВ
# =============================================================================

@dataclass
class ExpenseItem:
    """Детализация одного расхода."""
    expense_id: int
    expense_name: str
    expense_type: str  # physical/overhead
    quantity: Decimal  # для физических
    unit_price: Decimal  # для физических
    total_cost: Decimal


@dataclass
class ProductionCalculationResult:
    """
    Результат расчёта производства.

    ИСПОЛЬЗУЕТСЯ для ОБОИХ сценариев:
    - calculate_from_quantity()
    - calculate_from_suzerain()
    """
    product: Product
    quantity_produced: Decimal

    # Расходы
    physical_expenses: List[ExpenseItem]
    overhead_expenses: List[ExpenseItem]

    # Суммы
    total_physical_cost: Decimal
    total_overhead_cost: Decimal
    total_cost: Decimal
    cost_per_unit: Decimal

    # Прибыль
    markup_percentage: Decimal
    final_price: Decimal
    profit_per_unit: Decimal


@dataclass
class OverheadDistribution:
    """Результат распределения накладных расходов."""
    product_id: int
    product_name: str
    volume_produced: Decimal
    volume_share: Decimal  # доля от общего объёма (0-1)
    overhead_share: Decimal  # сумма накладных расходов


# =============================================================================
# PRODUCTION CALCULATOR (ТЗ 4.1.3)
# =============================================================================

class ProductionCalculator:
    """
    Калькулятор производства с двумя сценариями (ТЗ 4.1.3).

    СЦЕНАРИЙ 1: Ввод количества товара
        calculate_from_quantity(product, 200) → расходы

    СЦЕНАРИЙ 2: Ввод объёма Сюзерена
        calculate_from_suzerain(product, Фарш, 2кг) → количество + расходы
    """

    @classmethod
    def calculate_from_quantity(
            cls,
            product: Product,
            quantity: Decimal
    ) -> ProductionCalculationResult:
        """
        Сценарий 1: Ввод количества товара (ТЗ 4.1.3).

        ПРИМЕР: 200 пельменей
        1. Находим Сюзерена (Фарш): 200 × 0.01 = 2 кг
        2. Вычисляем пропорции: Лук (50%), Тесто (100%)
        3. Рассчитываем стоимость каждого расхода
        4. Распределяем накладные по объёму производства

        Args:
            product: Товар
            quantity: Количество товара

        Returns:
            ProductionCalculationResult
        """
        # Получаем рецепт товара
        recipe_items = ProductRecipe.objects.filter(
            product=product
        ).select_related('expense')

        if not recipe_items.exists():
            raise ValueError(f'У товара {product.name} нет рецепта')

        # Находим Сюзерена
        suzerain_item = recipe_items.filter(
            expense__expense_status=ExpenseStatus.SUZERAIN
        ).first()

        if not suzerain_item:
            raise ValueError(f'У товара {product.name} нет Сюзерена')

        # Рассчитываем объём Сюзерена
        suzerain_quantity = quantity * suzerain_item.quantity_per_unit

        # Теперь вызываем общий метод расчёта
        return cls._calculate_expenses(
            product=product,
            quantity=quantity,
            suzerain_item=suzerain_item,
            suzerain_quantity=suzerain_quantity
        )

    @classmethod
    def calculate_from_suzerain(
            cls,
            product: Product,
            suzerain_quantity: Decimal
    ) -> ProductionCalculationResult:
        """
        Сценарий 2: Ввод объёма Сюзерена (ТЗ 4.1.3).

        ПРИМЕР: 2 кг фарша
        1. Находим Сюзерена (Фарш)
        2. Вычисляем количество: 2 / 0.01 = 200 пельменей
        3. Далее аналогично сценарию 1

        Args:
            product: Товар
            suzerain_quantity: Количество Сюзерена (кг/шт)

        Returns:
            ProductionCalculationResult
        """
        # Получаем рецепт
        recipe_items = ProductRecipe.objects.filter(
            product=product
        ).select_related('expense')

        # Находим Сюзерена
        suzerain_item = recipe_items.filter(
            expense__expense_status=ExpenseStatus.SUZERAIN
        ).first()

        if not suzerain_item:
            raise ValueError(f'У товара {product.name} нет Сюзерена')

        # Вычисляем количество товара
        quantity = suzerain_quantity / suzerain_item.quantity_per_unit

        # Вызываем общий метод
        return cls._calculate_expenses(
            product=product,
            quantity=quantity,
            suzerain_item=suzerain_item,
            suzerain_quantity=suzerain_quantity
        )

    @classmethod
    def _calculate_expenses(
            cls,
            product: Product,
            quantity: Decimal,
            suzerain_item: ProductRecipe,
            suzerain_quantity: Decimal
    ) -> ProductionCalculationResult:
        """
        Общий метод расчёта расходов.

        1. Физические расходы (с пропорциями)
        2. Накладные расходы (распределение по объёму)
        3. Универсальные расходы
        """
        physical_expenses = []
        overhead_expenses = []

        # =====================================================================
        # 1. ФИЗИЧЕСКИЕ РАСХОДЫ
        # =====================================================================

        # Сюзерен
        suzerain_cost = (
                suzerain_quantity * (suzerain_item.expense.price_per_unit or Decimal('0'))
        ).quantize(Decimal('0.01'))

        physical_expenses.append(ExpenseItem(
            expense_id=suzerain_item.expense.id,
            expense_name=suzerain_item.expense.name,
            expense_type='physical',
            quantity=suzerain_quantity,
            unit_price=suzerain_item.expense.price_per_unit or Decimal('0'),
            total_cost=suzerain_cost
        ))

        # Остальные физические (пропорции от Сюзерена)
        recipe_items = ProductRecipe.objects.filter(
            product=product,
            expense__expense_type=ExpenseType.PHYSICAL
        ).exclude(
            expense__expense_status=ExpenseStatus.SUZERAIN
        ).select_related('expense')

        for item in recipe_items:
            if item.proportion:
                # Количество = Сюзерен × пропорция
                item_quantity = suzerain_quantity * item.proportion
                item_cost = (
                        item_quantity * (item.expense.price_per_unit or Decimal('0'))
                ).quantize(Decimal('0.01'))

                physical_expenses.append(ExpenseItem(
                    expense_id=item.expense.id,
                    expense_name=item.expense.name,
                    expense_type='physical',
                    quantity=item_quantity,
                    unit_price=item.expense.price_per_unit or Decimal('0'),
                    total_cost=item_cost
                ))

        total_physical = sum(item.total_cost for item in physical_expenses)

        # =====================================================================
        # 2. НАКЛАДНЫЕ РАСХОДЫ (умная наценка)
        # =====================================================================

        # Получаем долю накладных для этого товара
        overhead_share = OverheadDistributor.get_overhead_for_product(
            product=product,
            quantity_produced=quantity
        )

        # Добавляем в список (без детализации по каждому расходу)
        overhead_expenses.append(ExpenseItem(
            expense_id=0,
            expense_name='Накладные расходы (общие)',
            expense_type='overhead',
            quantity=Decimal('0'),
            unit_price=Decimal('0'),
            total_cost=overhead_share
        ))

        total_overhead = overhead_share

        # =====================================================================
        # 3. ИТОГО
        # =====================================================================

        total_cost = total_physical + total_overhead
        cost_per_unit = (total_cost / quantity).quantize(Decimal('0.01')) if quantity > 0 else Decimal('0')

        # Прибыль
        markup_percentage = product.markup_percentage
        markup_multiplier = Decimal('1') + (markup_percentage / 100)
        final_price = (cost_per_unit * markup_multiplier).quantize(Decimal('0.01'))
        profit_per_unit = final_price - cost_per_unit

        return ProductionCalculationResult(
            product=product,
            quantity_produced=quantity,
            physical_expenses=physical_expenses,
            overhead_expenses=overhead_expenses,
            total_physical_cost=total_physical,
            total_overhead_cost=total_overhead,
            total_cost=total_cost,
            cost_per_unit=cost_per_unit,
            markup_percentage=markup_percentage,
            final_price=final_price,
            profit_per_unit=profit_per_unit
        )


# =============================================================================
# OVERHEAD DISTRIBUTOR (ТЗ 4.1.4 - Умная наценка)
# =============================================================================

class OverheadDistributor:
    """
    Распределитель накладных расходов по объёму производства (ТЗ 4.1.4).

    ПРИМЕР:
    Пельмени зелёные: 1000 шт/день (популярные)
    Пельмени красные: 100 шт/день (непопулярные)
    Аренда: 10,000 сом/день

    Распределение НЕ ПОРОВНУ (5000/5000), а по объёму:
    - Зелёные: 90.9% = 9,090 сом
    - Красные: 9.1% = 910 сом
    """

    @classmethod
    def get_overhead_for_product(
            cls,
            product: Product,
            quantity_produced: Decimal,
            date_filter: Optional[date] = None
    ) -> Decimal:
        """
        Получить долю накладных расходов для товара.

        Args:
            product: Товар
            quantity_produced: Количество производства
            date_filter: Дата (опционально)

        Returns:
            Сумма накладных расходов
        """
        # Получаем все накладные расходы
        overhead_expenses = Expense.objects.filter(
            expense_type=ExpenseType.OVERHEAD,
            is_active=True
        )

        if not overhead_expenses.exists():
            return Decimal('0')

        # Считаем общую сумму накладных
        total_overhead = Decimal('0')
        for expense in overhead_expenses:
            total_overhead += expense.calculate_amount()

        # Получаем объёмы производства всех товаров
        all_products_volumes = cls._get_all_products_volumes(date_filter)

        # Вычисляем долю текущего товара
        total_volume = sum(v['volume'] for v in all_products_volumes)

        if total_volume == 0:
            # Если нет данных о производстве, делим поровну
            active_products_count = Product.objects.filter(is_active=True).count()
            if active_products_count > 0:
                return (total_overhead / active_products_count).quantize(Decimal('0.01'))
            else:
                return Decimal('0')

        # Находим текущий товар в списке
        current_product_volume = next(
            (v for v in all_products_volumes if v['product_id'] == product.id),
            None
        )

        if current_product_volume:
            volume = current_product_volume['volume']
        else:
            # Если товар ещё не производился, используем текущее количество
            volume = quantity_produced
            total_volume += volume

        # Вычисляем долю
        share = volume / total_volume if total_volume > 0 else Decimal('0')
        overhead_share = (total_overhead * share).quantize(Decimal('0.01'))

        return overhead_share

    @classmethod
    def _get_all_products_volumes(
            cls,
            date_filter: Optional[date] = None
    ) -> List[Dict]:
        """
        Получить объёмы производства всех товаров.

        Args:
            date_filter: Дата (если None, берём последний месяц)

        Returns:
            [{'product_id': 1, 'product_name': 'Пельмени', 'volume': 1000}, ...]
        """
        from datetime import timedelta

        # Если дата не указана, берём последний месяц
        if not date_filter:
            date_filter = date.today()

        start_date = date_filter - timedelta(days=30)

        # Получаем производство за период
        batches = ProductionBatch.objects.filter(
            date__gte=start_date,
            date__lte=date_filter
        ).values('product__id', 'product__name').annotate(
            total_volume=Sum('quantity_produced')
        )

        return [
            {
                'product_id': batch['product__id'],
                'product_name': batch['product__name'],
                'volume': batch['total_volume']
            }
            for batch in batches
        ]

    @classmethod
    def distribute_overhead_for_all(
            cls,
            products_with_volumes: List[Tuple[Product, Decimal]]
    ) -> List[OverheadDistribution]:
        """
        Распределить накладные расходы для всех товаров.

        Args:
            products_with_volumes: [(product, volume), ...]

        Returns:
            [OverheadDistribution, ...]
        """
        # Получаем общую сумму накладных
        total_overhead = Decimal('0')
        overhead_expenses = Expense.objects.filter(
            expense_type=ExpenseType.OVERHEAD,
            is_active=True
        )

        for expense in overhead_expenses:
            total_overhead += expense.calculate_amount()

        # Вычисляем общий объём
        total_volume = sum(volume for _, volume in products_with_volumes)

        if total_volume == 0:
            return []

        # Распределяем
        results = []
        for product, volume in products_with_volumes:
            share = volume / total_volume
            overhead_share = (total_overhead * share).quantize(Decimal('0.01'))

            results.append(OverheadDistribution(
                product_id=product.id,
                product_name=product.name,
                volume_produced=volume,
                volume_share=share,
                overhead_share=overhead_share
            ))

        return results


# =============================================================================
# EXPENSE SERVICE (иерархия Сюзерен/Вассал/Обыватель)
# =============================================================================

class ExpenseService:
    """Сервис для работы с расходами."""

    @classmethod
    def calculate_total_expenses_with_hierarchy(cls) -> Decimal:
        """
        Рассчитать общие расходы с учётом иерархии.

        Returns:
            Общая сумма расходов
        """
        total = Decimal('0')

        expenses = Expense.objects.filter(is_active=True)

        for expense in expenses:
            total += expense.calculate_amount()

        return total

    @classmethod
    def get_expense_breakdown(cls) -> Dict[str, List[Dict]]:
        """
        Получить детализацию расходов.

        Returns:
            {
                'physical': [...],
                'overhead': [...]
            }
        """
        expenses = Expense.objects.filter(is_active=True)

        physical = []
        overhead = []

        for expense in expenses:
            item = {
                'id': expense.id,
                'name': expense.name,
                'status': expense.expense_status,
                'amount': float(expense.calculate_amount())
            }

            if expense.expense_type == ExpenseType.PHYSICAL:
                physical.append(item)
            else:
                overhead.append(item)

        return {
            'physical': physical,
            'overhead': overhead
        }


# =============================================================================
# PRODUCTION SERVICE (создание партий)
# =============================================================================

class ProductionService:
    """Сервис для создания производственных партий."""

    @classmethod
    @transaction.atomic
    def create_batch_from_quantity(
            cls,
            product_id: int,
            quantity: Decimal,
            date: date,
            notes: str = ''
    ) -> ProductionBatch:
        """
        Создать партию от количества товара (сценарий 1).

        Args:
            product_id: ID товара
            quantity: Количество товара
            date: Дата производства
            notes: Заметки

        Returns:
            ProductionBatch
        """
        product = Product.objects.get(pk=product_id)

        # Рассчитываем
        result = ProductionCalculator.calculate_from_quantity(product, quantity)

        # Создаём партию
        batch = ProductionBatch.objects.create(
            product=product,
            date=date,
            quantity_produced=result.quantity_produced,
            total_physical_cost=result.total_physical_cost,
            total_overhead_cost=result.total_overhead_cost,
            cost_per_unit=result.cost_per_unit,
            input_type='quantity',
            notes=notes
        )

        return batch

    @classmethod
    @transaction.atomic
    def create_batch_from_suzerain(
            cls,
            product_id: int,
            suzerain_quantity: Decimal,
            date: date,
            notes: str = ''
    ) -> ProductionBatch:
        """
        Создать партию от объёма Сюзерена (сценарий 2).

        Args:
            product_id: ID товара
            suzerain_quantity: Количество Сюзерена (кг/шт)
            date: Дата производства
            notes: Заметки

        Returns:
            ProductionBatch
        """
        product = Product.objects.get(pk=product_id)

        # Рассчитываем
        result = ProductionCalculator.calculate_from_suzerain(product, suzerain_quantity)

        # Создаём партию
        batch = ProductionBatch.objects.create(
            product=product,
            date=date,
            quantity_produced=result.quantity_produced,
            total_physical_cost=result.total_physical_cost,
            total_overhead_cost=result.total_overhead_cost,
            cost_per_unit=result.cost_per_unit,
            input_type='suzerain',
            notes=notes
        )

        return batch