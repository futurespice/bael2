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
from django.db.models import Sum, Q, F

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
    def _load_recipe(cls, product: Product) -> List[ProductRecipe]:
        """Загрузить рецепт товара одним запросом (используется в обоих сценариях)."""
        return list(
            ProductRecipe.objects.filter(product=product).select_related('expense')
        )

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
        """
        # BUG FIX: загружаем все рецепты ОДНИМ запросом
        all_recipes = cls._load_recipe(product)

        if not all_recipes:
            raise ValueError(f'У товара {product.name} нет рецепта')

        suzerain_item = next(
            (r for r in all_recipes if r.expense.expense_status == ExpenseStatus.SUZERAIN),
            None
        )
        if not suzerain_item:
            raise ValueError(f'У товара {product.name} нет Сюзерена')

        if not suzerain_item.quantity_per_unit or suzerain_item.quantity_per_unit <= 0:
            raise ValueError(
                f'У Сюзерена "{suzerain_item.expense.name}" не задана норма на единицу '
                f'(quantity_per_unit). Обновите рецепт товара.'
            )
        suzerain_quantity = quantity * suzerain_item.quantity_per_unit

        return cls._calculate_expenses(
            product=product,
            quantity=quantity,
            suzerain_item=suzerain_item,
            suzerain_quantity=suzerain_quantity,
            all_recipes=all_recipes,
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
        """
        all_recipes = cls._load_recipe(product)

        suzerain_item = next(
            (r for r in all_recipes if r.expense.expense_status == ExpenseStatus.SUZERAIN),
            None
        )
        if not suzerain_item:
            raise ValueError(f'У товара {product.name} нет Сюзерена')

        if not suzerain_item.quantity_per_unit or suzerain_item.quantity_per_unit <= 0:
            # Fallback: вычислить quantity_per_unit из absolute_quantity / product_quantity
            if (suzerain_item.absolute_quantity and suzerain_item.product_quantity
                    and suzerain_item.product_quantity > 0):
                suzerain_item.quantity_per_unit = (
                    suzerain_item.absolute_quantity / suzerain_item.product_quantity
                ).quantize(Decimal('0.0001'))
            else:
                raise ValueError(
                    f'У Сюзерена "{suzerain_item.expense.name}" не задана норма на единицу '
                    f'(quantity_per_unit). Введите количество товара (product_quantity) '
                    f'при настройке рецепта.'
                )
        quantity = suzerain_quantity / suzerain_item.quantity_per_unit

        return cls._calculate_expenses(
            product=product,
            quantity=quantity,
            suzerain_item=suzerain_item,
            suzerain_quantity=suzerain_quantity,
            all_recipes=all_recipes,
        )

    @classmethod
    def _calculate_expenses(
            cls,
            product: Product,
            quantity: Decimal,
            suzerain_item: ProductRecipe,
            suzerain_quantity: Decimal,
            all_recipes: List[ProductRecipe],
    ) -> ProductionCalculationResult:
        """
        Общий метод расчёта расходов.

        Принимает уже загруженный список рецептов (all_recipes),
        чтобы избежать N+1 запросов к БД.
        """
        physical_expenses = []

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

        # Остальные физические — из уже загруженного all_recipes (без нового запроса к БД)
        other_physical_recipes = [
            r for r in all_recipes
            if r.expense.expense_type == ExpenseType.PHYSICAL
            and r.expense.expense_status != ExpenseStatus.SUZERAIN
        ]

        for item in other_physical_recipes:  # BUG FIX: было recipe_items (NameError)
            if item.proportion:
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
            elif item.quantity_per_unit:
                # Универсальный физический (пленка): quantity_per_unit задан напрямую
                # Используем quantity напрямую, т.к. suzerain_quantity / suzerain_qpu = quantity
                item_quantity = quantity * item.quantity_per_unit
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
        # 2. НАКЛАДНЫЕ РАСХОДЫ (умная наценка с детализацией)
        # =====================================================================

        # ТЗ Бахрам акя: показываем КАЖДЫЙ накладной расход отдельно
        overhead_expenses = OverheadDistributor.get_overhead_breakdown_for_product(
            product=product,
            quantity_produced=quantity
        )

        total_overhead = sum(item.total_cost for item in overhead_expenses)

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
            date_filter: Optional[date] = None,
            period_days: int = 11  # 1.5 недели
    ) -> Decimal:
        """
        Получить долю накладных расходов для товара на основе ПРОДАЖ.

        ТЗ Бахрам акя: накладные распределяются пропорционально объёму продаж,
        не производства. Товары которые продаются чаще — несут больше расходов.

        Args:
            product: Товар
            quantity_produced: Количество для расчёта (если товар новый)
            date_filter: Конечная дата анализа
            period_days: Период анализа (по умолчанию 11 дней = 1.5 недели)

        Returns:
            Сумма накладных расходов для данного товара
        """
        # Один запрос вместо двух (.exists() + итерация)
        overhead_expenses = list(Expense.objects.filter(
            expense_type=ExpenseType.OVERHEAD,
            is_active=True
        ))

        if not overhead_expenses:
            return Decimal('0')

        # Считаем общую сумму накладных за день
        total_overhead = Decimal('0')
        for expense in overhead_expenses:
            total_overhead += expense.calculate_amount()

        # Получаем объёмы ПРОДАЖ всех товаров за период
        all_products_volumes = cls._get_all_products_volumes(
            date_filter=date_filter,
            period_days=period_days
        )

        # Вычисляем долю текущего товара
        total_volume = sum(v['volume'] for v in all_products_volumes)

        if total_volume == 0:
            # Если нет данных о продажах, делим поровну
            active_products_count = Product.objects.filter(is_active=True).count()
            if active_products_count > 0:
                return (total_overhead / active_products_count).quantize(Decimal('0.01'))
            else:
                return Decimal('0')

        # Находим текущий товар в списке продаж
        current_product_volume = next(
            (v for v in all_products_volumes if v['product_id'] == product.id),
            None
        )

        if current_product_volume:
            volume = current_product_volume['volume']
        else:
            # Если товар ещё не продавался, используем введённое количество
            volume = quantity_produced
            total_volume += volume

        # Вычисляем долю
        share = volume / total_volume if total_volume > 0 else Decimal('0')
        overhead_share = (total_overhead * share).quantize(Decimal('0.01'))

        return overhead_share

    @classmethod
    def _get_all_products_volumes(
            cls,
            date_filter: Optional[date] = None,
            period_days: int = 11  # 1.5 недели по умолчанию
    ) -> List[Dict]:
        """
        Получить объёмы ПРОДАЖ всех товаров (не производства!).

        ТЗ Бахрам акя: распределять накладные на основе реальных продаж,
        а не производства. Товары которые продаются чаще — несут больше
        накладных расходов.

        Args:
            date_filter: Конечная дата (если None, берём сегодня)
            period_days: Период анализа в днях (по умолчанию 11 дней = 1.5 недели)

        Returns:
            [{'product_id': 1, 'product_name': 'Пельмени', 'volume': 1000, 'revenue': 50000}, ...]
        """
        from datetime import timedelta
        from orders.models import StoreOrderItem, StoreOrderStatus

        # Если дата не указана, берём сегодня
        if not date_filter:
            date_filter = date.today()

        start_date = date_filter - timedelta(days=period_days)

        # Получаем ПРОДАЖИ за период (из заказов магазинов)
        # Учитываем только доставленные заказы
        sales = StoreOrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=date_filter,
            order__status__in=[
                StoreOrderStatus.ACCEPTED
            ],
            is_bonus=False  # Не учитываем бонусные товары
        ).values(
            'product__id',
            'product__name'
        ).annotate(
            total_volume=Sum('quantity'),
            total_revenue=Sum('total')
        )

        return [
            {
                'product_id': sale['product__id'],
                'product_name': sale['product__name'],
                'volume': sale['total_volume'] or Decimal('0'),
                'revenue': sale['total_revenue'] or Decimal('0')
            }
            for sale in sales
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

    @classmethod
    def get_overhead_breakdown_for_product(
            cls,
            product: Product,
            quantity_produced: Decimal,
            date_filter: Optional[date] = None,
            period_days: int = 11
    ) -> List[ExpenseItem]:
        """
        Получить ДЕТАЛИЗАЦИЮ накладных расходов для товара.

        ТЗ: разделяем universal и regular overhead:
        - Universal: доля среди ВСЕХ активных товаров
        - Regular: доля только среди ПРИВЯЗАННЫХ товаров (галочка при создании товара)

        Args:
            product: Товар
            quantity_produced: Количество для расчёта (если нет истории продаж)
            date_filter: Конечная дата анализа
            period_days: Период анализа в днях

        Returns:
            Список ExpenseItem с детализацией по каждому накладному расходу
        """
        overhead_expenses = list(Expense.objects.filter(
            expense_type=ExpenseType.OVERHEAD,
            is_active=True
        ))

        if not overhead_expenses:
            return []

        # Объёмы продаж за период (один запрос к БД)
        all_products_volumes = cls._get_all_products_volumes(
            date_filter=date_filter,
            period_days=period_days
        )
        volume_by_product_id = {v['product_id']: v['volume'] for v in all_products_volumes}
        total_volume_all = sum(volume_by_product_id.values()) or Decimal('0')

        # Объём текущего товара
        product_volume = volume_by_product_id.get(product.id, Decimal('0'))

        # Глобальная доля товара среди всех (для universal)
        if total_volume_all > 0:
            # Есть реальные продажи — распределяем пропорционально.
            # Если этот товар не продавался, его доля = 0 (overhead не добавляем).
            # Это корректно: накладные несут те, кто генерирует выручку.
            universal_share = product_volume / total_volume_all
        else:
            # Нет продаж ни у кого — делим overhead поровну между активными товарами.
            # Раньше здесь добавляли quantity_produced в total_volume_all → доля = 100% (БАГ).
            active_count = Product.objects.filter(is_active=True).count() or 1
            universal_share = Decimal('1') / active_count

        # Привязки regular-расходов к товарам (один запрос к БД)
        regular_expense_ids = [
            e.id for e in overhead_expenses if e.apply_type == ApplyType.REGULAR
        ]
        # {expense_id: set(product_ids)} — кому привязан каждый regular-расход
        regular_linked: dict = {}
        if regular_expense_ids:
            for rec in ProductRecipe.objects.filter(
                expense_id__in=regular_expense_ids
            ).values('expense_id', 'product_id'):
                regular_linked.setdefault(rec['expense_id'], set()).add(rec['product_id'])

        breakdown = []
        for expense in overhead_expenses:
            expense_amount = expense.calculate_amount()

            if expense.apply_type == ApplyType.UNIVERSAL:
                # Universal: доля среди ВСЕХ товаров
                product_share = (expense_amount * universal_share).quantize(Decimal('0.01'))
            else:
                # Regular: только если товар привязан галочкой
                linked_ids = regular_linked.get(expense.id, set())
                if product.id not in linked_ids:
                    continue  # этот расход не касается данного товара

                # Объём среди привязанных товаров
                total_linked_vol = sum(
                    volume_by_product_id.get(pid, Decimal('0')) for pid in linked_ids
                )
                if total_linked_vol > 0:
                    regular_share = volume_by_product_id.get(product.id, Decimal('0')) / total_linked_vol
                else:
                    regular_share = Decimal('1') / max(len(linked_ids), 1)
                product_share = (expense_amount * regular_share).quantize(Decimal('0.01'))

            breakdown.append(ExpenseItem(
                expense_id=expense.id,
                expense_name=expense.name,
                expense_type='overhead',
                quantity=Decimal('0'),
                unit_price=expense_amount,
                total_cost=product_share
            ))

        return breakdown


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

        # Обновляем склад атомарно (F-expression предотвращает race condition).
        Product.objects.filter(pk=product.pk).update(
            stock_quantity=F('stock_quantity') + result.quantity_produced
        )
        product.refresh_from_db(fields=['stock_quantity'])
        product.update_average_cost_price()

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

        # Обновляем склад атомарно (F-expression предотвращает race condition).
        Product.objects.filter(pk=product.pk).update(
            stock_quantity=F('stock_quantity') + result.quantity_produced
        )
        product.refresh_from_db(fields=['stock_quantity'])
        product.update_average_cost_price()

        return batch


# =============================================================================
# ACCOUNTING SERVICE (Экран "Учёт данных")
# =============================================================================

class AccountingService:
    """Сервис для сохранения данных учёта (механика + котлован + партии)."""

    @classmethod
    @transaction.atomic
    def save_accounting_data(cls, mechanical_expenses_data, recipe_items_data, production_batches_data):
        results = {'mechanical_updated': 0, 'recipes_saved': 0, 'batches_created': 0}

        # 1. Валидация и обновление daily_amount для механических расходов
        mech_expense_ids = [item['expense_id'] for item in mechanical_expenses_data]
        mech_expenses_map = {e.id: e for e in Expense.objects.filter(id__in=mech_expense_ids)}

        for item in mechanical_expenses_data:
            expense = mech_expenses_map.get(item['expense_id'])
            if expense is None:
                raise ValueError(f"Расход с id={item['expense_id']} не найден")

            # ТЗ: в механический учёт принимаются ТОЛЬКО Вассалы
            # Вассал = overhead + mechanical + universal (expense_status=vassal)
            if expense.expense_type != 'overhead':
                raise ValueError(
                    f"Расход '{expense.name}' (id={expense.id}) является физическим. "
                    f"В механический учёт передаются ТОЛЬКО накладные расходы."
                )
            if expense.expense_state != 'mechanical':
                raise ValueError(
                    f"Расход '{expense.name}' (id={expense.id}) не является механическим "
                    f"(состояние: {expense.expense_state})"
                )
            # BUG FIX: добавляем проверку apply_type=universal.
            # overhead + mechanical + regular проходил валидацию, но не является Вассалом.
            if expense.apply_type != 'universal':
                raise ValueError(
                    f"Расход '{expense.name}' (id={expense.id}) не является универсальным. "
                    f"Механический учёт работает только для Vassal (overhead+mechanical+universal)."
                )

            expense.daily_amount = item['amount']
            expense.save(update_fields=['daily_amount'])
            results['mechanical_updated'] += 1

        # 2. Котлованская часть — создать/обновить рецепты товаров
        #
        # BUG FIX: Сюзерены обрабатываются ПЕРВЫМИ.
        # ProductRecipe.save() для не-Сюзерена ищет Сюзерена в БД, чтобы рассчитать
        # proportion = absolute_quantity / suzerain.absolute_quantity.
        # Если не-Сюзерен идёт первым, Сюзерен ещё не записан — proportion останется None.

        # Загружаем expense_status для всех recipe_items (один bulk-запрос)
        expense_ids = [item['expense_id'] for item in recipe_items_data]
        expense_statuses = {
            e.id: e.expense_status
            for e in Expense.objects.filter(id__in=expense_ids).only('id', 'expense_status')
        }

        # Сортируем: Сюзерены первыми, остальные потом
        sorted_recipe_items = sorted(
            recipe_items_data,
            key=lambda x: 0 if expense_statuses.get(x['expense_id']) == ExpenseStatus.SUZERAIN else 1
        )

        # Bulk-проверка товаров одним запросом вместо N запросов per item
        recipe_product_ids = [item['product_id'] for item in sorted_recipe_items]
        valid_product_ids = set(
            Product.objects.filter(id__in=recipe_product_ids).values_list('id', flat=True)
        )

        for item in sorted_recipe_items:
            if item['product_id'] not in valid_product_ids:
                raise ValueError(f"Товар с id={item['product_id']} не найден")
            if item['expense_id'] not in expense_statuses:
                raise ValueError(f"Расход с id={item['expense_id']} не найден")

            defaults = {}
            if item.get('absolute_quantity') is not None:
                defaults['absolute_quantity'] = item['absolute_quantity']
            if item.get('product_quantity') is not None:
                defaults['product_quantity'] = item['product_quantity']
            if item.get('quantity_per_unit') is not None:
                defaults['quantity_per_unit'] = item['quantity_per_unit']
            if item.get('proportion') is not None:
                defaults['proportion'] = item['proportion']

            # update_or_create внутри вызывает save(), который автоматически
            # рассчитывает proportion/quantity_per_unit из absolute_quantity.
            # Дополнительный recipe.save() НЕ нужен.
            ProductRecipe.objects.update_or_create(
                product_id=item['product_id'],
                expense_id=item['expense_id'],
                defaults=defaults
            )
            results['recipes_saved'] += 1

        # 3a. Авто-создание партий из котлованских recipe_items.
        #
        # Когда пользователь в котлованском режиме пишет "200 пельменей" (product_quantity),
        # система должна сразу создать ProductionBatch и обновить склад.
        # Если партия для этого товара на сегодня уже есть — перезаписываем (overwrite-режим):
        #   - удаляем старую (через delete() автоматически вычитается stock_quantity)
        #   - создаём новую с новым количеством
        #
        # Это позволяет корректировать: написал 200, потом изменил на 150 — на складе станет 150.

        today = date.today()
        # Собираем: product_id → product_quantity для суверенов с product_quantity
        auto_batch_products: dict = {}
        for item in sorted_recipe_items:
            if expense_statuses.get(item['expense_id']) == ExpenseStatus.SUZERAIN:
                pq = item.get('product_quantity')
                if pq is not None and Decimal(str(pq)) > 0:
                    auto_batch_products[item['product_id']] = Decimal(str(pq))
                elif item.get('absolute_quantity') is not None:
                    # Если есть absolute_quantity без product_quantity —
                    # вычисляем количество через quantity_per_unit из сохранённого рецепта
                    aq = Decimal(str(item['absolute_quantity']))
                    if aq > 0:
                        recipe = ProductRecipe.objects.filter(
                            product_id=item['product_id'],
                            expense_id=item['expense_id']
                        ).first()
                        if recipe and recipe.quantity_per_unit and recipe.quantity_per_unit > 0:
                            computed_pq = (aq / recipe.quantity_per_unit).quantize(Decimal('0.01'))
                            if computed_pq > 0:
                                auto_batch_products[item['product_id']] = computed_pq

        # ID товаров, для которых явно передан production_batches (не трогаем их auto-логикой)
        explicit_batch_product_ids = {item['product_id'] for item in production_batches_data}

        for product_id, product_quantity in auto_batch_products.items():
            if product_id in explicit_batch_product_ids:
                continue  # явная партия приоритетнее авто-режима

            # Удаляем существующие партии за сегодня (перезапись)
            existing_today = ProductionBatch.objects.filter(
                product_id=product_id,
                date=today
            )
            for old_batch in existing_today:
                old_batch.delete()  # delete() автоматически вычитает stock_quantity

            ProductionService.create_batch_from_quantity(
                product_id=product_id,
                quantity=product_quantity,
                date=today,
                notes='Авто-партия из котлованского режима'
            )
            results['batches_created'] += 1

        # 3b. Явные производственные партии (ДОБАВЛЯЮТСЯ к существующим)
        for item in production_batches_data:
            batch_date = item.get('date', today)
            notes = item.get('notes', '')

            if item['input_type'] == 'quantity':
                ProductionService.create_batch_from_quantity(
                    product_id=item['product_id'],
                    quantity=item['quantity'],
                    date=batch_date,
                    notes=notes
                )
            else:
                ProductionService.create_batch_from_suzerain(
                    product_id=item['product_id'],
                    suzerain_quantity=item['suzerain_quantity'],
                    date=batch_date,
                    notes=notes
                )
            results['batches_created'] += 1

        return results