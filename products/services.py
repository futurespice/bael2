# apps/products/services.py
"""
Сервисный слой для модуля products.

Содержит бизнес-логику:
- CostCalculator: Расчёт себестоимости товаров
- RecipeService: Управление рецептами (котловой метод)
- SnapshotService: Обновление кеша себестоимости
- BonusService: Система бонусов (каждый 21-й товар бесплатно)

Соответствует ТЗ БайЭл: раздел 4.1
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from django.db import transaction
from django.db.models import Sum, F, Value, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    Product,
    Expense,
    Recipe,
    ProductExpenseRelation,
    ProductCostSnapshot,
    ProductionRecord,
    ProductionItem,
    MechanicalExpenseEntry,
    StoreProductCounter,
    BonusHistory,
    ExpenseType,
    ExpenseStatus,
    ExpenseState,
    AccountingMode,
)

if TYPE_CHECKING:
    from orders.models import StoreOrder, StoreOrderItem

# =============================================================================
# КОНСТАНТЫ
# =============================================================================

DAYS_IN_MONTH = Decimal('30')
BONUS_THRESHOLD = 21  # Каждый 21-й товар бесплатно


# =============================================================================
# СЕРВИС: РАСЧЁТ СЕБЕСТОИМОСТИ
# =============================================================================

class CostCalculator:
    """
    Сервис расчёта себестоимости товаров.

    Реализует логику из ТЗ 4.1:
    - Расчёт себестоимости из рецептов (ингредиенты)
    - Умная наценка накладных расходов (пропорционально популярности)
    - Автоматическое применение наценки к итоговой цене

    Пример использования:
        # Расчёт себестоимости товара
        cost = CostCalculator.calculate_product_cost(product)

        # Пересчёт позиции производства
        CostCalculator.calculate_production_item(item)

        # Обновление кеша себестоимости
        CostCalculator.update_product_snapshot(product)
    """

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ
    # =========================================================================

    @classmethod
    def calculate_product_cost(cls, product: Product) -> Decimal:
        """
        Рассчитать себестоимость одной единицы товара.

        Себестоимость = сумма (пропорция × цена ингредиента) для всех рецептов.

        Args:
            product: Товар для расчёта

        Returns:
            Себестоимость единицы товара
        """
        total_cost = Decimal('0')

        # Используем новую модель Recipe
        for recipe in product.recipes.select_related('expense').filter(
                expense__is_active=True
        ):
            if recipe.proportion > 0 and recipe.expense.price_per_unit:
                ingredient_cost = recipe.proportion * recipe.expense.price_per_unit
                total_cost += ingredient_cost

        # Fallback на legacy модель ProductExpenseRelation
        if total_cost == 0:
            for relation in product.expense_relations.select_related('expense').filter(
                    expense__is_active=True,
                    expense__expense_type=ExpenseType.PHYSICAL
            ):
                if relation.proportion > 0 and relation.expense.price_per_unit:
                    ingredient_cost = relation.proportion * relation.expense.price_per_unit
                    total_cost += ingredient_cost

        return total_cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    @transaction.atomic
    def update_product_cost_and_price(
            cls,
            product: Product,
            markup_percentage: Optional[Decimal] = None
    ) -> Product:
        """
        Пересчитать себестоимость и итоговую цену товара.

        1. Рассчитывает себестоимость из рецептов
        2. Применяет наценку (если указана или существующая)
        3. Обновляет final_price
        4. Помечает кеш как устаревший

        Args:
            product: Товар для обновления
            markup_percentage: Новый процент наценки (опционально)

        Returns:
            Обновлённый товар
        """
        # 1. Расчёт себестоимости
        cost_price = cls.calculate_product_cost(product)
        product.cost_price = cost_price

        # 2. Установка наценки
        if markup_percentage is not None:
            product.markup_percentage = markup_percentage

        # 3. Расчёт итоговой цены
        if product.cost_price > 0 and product.markup_percentage > 0:
            multiplier = Decimal('1') + (product.markup_percentage / Decimal('100'))
            product.final_price = (product.cost_price * multiplier).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        elif product.cost_price > 0:
            product.final_price = product.cost_price
        else:
            product.final_price = product.base_price

        # Синхронизация с legacy полем
        product.price = product.final_price

        # Пересчёт цены за 100г для весовых товаров
        if product.is_weight_based and product.final_price > 0:
            product.price_per_100g = (product.final_price / Decimal('10')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        # 4. Сохранение
        product.save(update_fields=[
            'cost_price', 'markup_percentage', 'final_price',
            'price', 'price_per_100g', 'updated_at'
        ])

        # 5. Пометить кеш как устаревший
        cls._mark_snapshot_outdated(product)

        return product

    @classmethod
    @transaction.atomic
    def calculate_production_item(cls, production_item: ProductionItem) -> ProductionItem:
        """
        Рассчитать себестоимость позиции производства.

        Полный расчёт по ТЗ 4.1:
        1. Количество товара (или расчёт из Сюзерена)
        2. Себестоимость ингредиентов
        3. Накладные расходы (умная наценка по популярности)
        4. Выручка и прибыль

        Args:
            production_item: Позиция производства

        Returns:
            Обновлённая позиция
        """
        record = production_item.record
        product = production_item.product
        quantity = production_item.quantity_produced or Decimal('0')

        # 1. Расчёт количества из Сюзерена (если указан)
        if production_item.suzerain_amount and production_item.suzerain_amount > 0:
            calculated_qty = cls._calculate_quantity_from_suzerain(
                product, production_item.suzerain_amount
            )
            if calculated_qty > 0:
                quantity = calculated_qty
                production_item.quantity_produced = quantity

        # Если количество <= 0, обнуляем все поля
        if quantity <= 0:
            production_item.ingredient_cost = Decimal('0')
            production_item.overhead_cost = Decimal('0')
            production_item.total_cost = Decimal('0')
            production_item.cost_price = Decimal('0')
            production_item.revenue = Decimal('0')
            production_item.net_profit = Decimal('0')
            production_item.save()
            return production_item

        # 2. Себестоимость ингредиентов
        ingredient_cost = cls._calculate_ingredient_cost(product, quantity)

        # 3. Накладные расходы (умная наценка)
        overhead_cost = cls._calculate_overhead_cost(record, product, quantity)

        # 4. Итоговые расчёты
        total_cost = (ingredient_cost + overhead_cost).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        cost_price = (total_cost / quantity).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        ) if quantity > 0 else Decimal('0')

        # Выручка по итоговой цене (с наценкой)
        revenue = (product.final_price * quantity).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        net_profit = (revenue - total_cost).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # 5. Сохранение
        production_item.ingredient_cost = ingredient_cost
        production_item.overhead_cost = overhead_cost
        production_item.total_cost = total_cost
        production_item.cost_price = cost_price
        production_item.revenue = revenue
        production_item.net_profit = net_profit
        production_item.save()

        return production_item

    @classmethod
    @transaction.atomic
    def recalculate_all_items(cls, record: ProductionRecord) -> List[ProductionItem]:
        """
        Пересчитать все позиции в записи производства.

        Используется после изменения расходов или популярности товаров.

        Args:
            record: Запись производства

        Returns:
            Список обновлённых позиций
        """
        items = list(
            ProductionItem.objects
            .filter(record=record)
            .select_related('product', 'record')
        )

        for item in items:
            cls.calculate_production_item(item)

        return items

    @classmethod
    @transaction.atomic
    def update_product_snapshot(cls, product: Product) -> ProductCostSnapshot:
        """
        Обновить кеш себестоимости товара.

        Создаёт или обновляет ProductCostSnapshot с актуальными данными
        для отображения в таблице себестоимости.

        Args:
            product: Товар

        Returns:
            Обновлённый снапшот
        """
        # Расчёт себестоимости
        cost_price = cls.calculate_product_cost(product)

        # Наценка
        markup_amount = Decimal('0')
        if product.markup_percentage > 0:
            markup_amount = (cost_price * product.markup_percentage / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        # Расходы на ингредиенты (детализация)
        ingredient_expense = cost_price

        # Накладные расходы (доля от общих)
        overhead_expense = cls._calculate_product_overhead_share(product)

        # Общий расход
        total_expense = (ingredient_expense + overhead_expense).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # Доход (на основе продаж за 30 дней)
        revenue = cls._calculate_product_revenue(product, days=30)

        # Прибыль
        profit = (revenue - total_expense).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # Создание или обновление снапшота
        snapshot, _ = ProductCostSnapshot.objects.update_or_create(
            product=product,
            defaults={
                'cost_price': cost_price,
                'markup_amount': markup_amount,
                'ingredient_expense': ingredient_expense,
                'overhead_expense': overhead_expense,
                'total_expense': total_expense,
                'revenue': revenue,
                'profit': profit,
                'is_outdated': False,
            }
        )

        return snapshot

    @classmethod
    def bulk_update_snapshots(cls, products: Optional[List[Product]] = None) -> int:
        """
        Массовое обновление кешей себестоимости.

        Args:
            products: Список товаров (или все с is_outdated=True)

        Returns:
            Количество обновлённых снапшотов
        """
        if products is None:
            # Получаем товары с устаревшими снапшотами
            outdated_ids = ProductCostSnapshot.objects.filter(
                is_outdated=True
            ).values_list('product_id', flat=True)

            products = list(Product.objects.filter(
                Q(id__in=outdated_ids) | ~Q(cost_snapshot__isnull=False),
                is_active=True
            ))

        count = 0
        for product in products:
            cls.update_product_snapshot(product)
            count += 1

        return count

    # =========================================================================
    # ПРИВАТНЫЕ МЕТОДЫ
    # =========================================================================

    @classmethod
    def _calculate_quantity_from_suzerain(
            cls,
            product: Product,
            suzerain_amount: Decimal
    ) -> Decimal:
        """
        Расчёт количества товара из объёма Сюзерена.

        Пример: 2 кг фарша → сколько пельменей можно произвести.

        Args:
            product: Товар
            suzerain_amount: Количество Сюзерена (кг/шт)

        Returns:
            Количество товара
        """
        # Ищем рецепт с Сюзереном
        suzerain_recipe = product.recipes.filter(
            expense__status=ExpenseStatus.SUZERAIN
        ).first()

        if suzerain_recipe and suzerain_recipe.proportion > 0:
            return (suzerain_amount / suzerain_recipe.proportion).quantize(
                Decimal('0.001'), rounding=ROUND_HALF_UP
            )

        # Fallback на legacy
        suzerain_relation = product.expense_relations.filter(
            expense__status=ExpenseStatus.SUZERAIN
        ).first()

        if suzerain_relation and suzerain_relation.proportion > 0:
            return (suzerain_amount / suzerain_relation.proportion).quantize(
                Decimal('0.001'), rounding=ROUND_HALF_UP
            )

        return Decimal('0')

    @classmethod
    def _calculate_ingredient_cost(cls, product: Product, quantity: Decimal) -> Decimal:
        """
        Расчёт стоимости ингредиентов для заданного количества товара.

        Args:
            product: Товар
            quantity: Количество

        Returns:
            Стоимость ингредиентов
        """
        cost = Decimal('0')

        # Используем Recipe
        for recipe in product.recipes.select_related('expense').filter(
                expense__is_active=True
        ):
            if recipe.proportion > 0 and recipe.expense.price_per_unit:
                cost += recipe.expense.price_per_unit * recipe.proportion * quantity

        # Fallback на legacy ProductExpenseRelation
        if cost == 0:
            for relation in product.expense_relations.select_related('expense').filter(
                    expense__is_active=True,
                    expense__expense_type=ExpenseType.PHYSICAL
            ):
                if relation.proportion > 0 and relation.expense.price_per_unit:
                    cost += relation.expense.price_per_unit * relation.proportion * quantity

        return cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    def _calculate_overhead_cost(
            cls,
            record: ProductionRecord,
            product: Product,
            quantity: Decimal
    ) -> Decimal:
        """
        Расчёт накладных расходов для позиции производства.

        Реализует "умную наценку" из ТЗ 4.1.4:
        Накладные распределяются пропорционально (количество × popularity_weight).

        Args:
            record: Запись производства
            product: Товар
            quantity: Количество

        Returns:
            Доля накладных расходов
        """
        if quantity <= 0:
            return Decimal('0')

        # Получаем все позиции за день для расчёта долей
        items = record.items.select_related('product').all()

        total_weighted_qty = Decimal('0')
        for item in items:
            if item.quantity_produced and item.quantity_produced > 0:
                weight = item.product.popularity_weight or Decimal('1.0')
                total_weighted_qty += item.quantity_produced * weight

        if total_weighted_qty <= 0:
            return Decimal('0')

        # Доля текущего товара
        product_weight = product.popularity_weight or Decimal('1.0')
        share = (quantity * product_weight) / total_weighted_qty

        # Общие накладные за день
        daily_overhead = cls._get_daily_overhead_total(record)

        return (daily_overhead * share).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    def _get_daily_overhead_total(cls, record: ProductionRecord) -> Decimal:
        """
        Получить общую сумму накладных расходов за день.

        Включает:
        - Автоматические: monthly_amount / 30
        - Механические: amount_spent из записей

        Args:
            record: Запись производства

        Returns:
            Сумма накладных за день
        """
        # Автоматические накладные (месячные / 30)
        auto_total = Expense.objects.filter(
            expense_type=ExpenseType.OVERHEAD,
            state=ExpenseState.AUTOMATIC,
            is_active=True
        ).exclude(
            monthly_amount__isnull=True
        ).aggregate(
            total=Coalesce(
                Sum(F('monthly_amount') / Value(DAYS_IN_MONTH)),
                Decimal('0')
            )
        )['total']

        # Механические накладные (из записей дня)
        mech_total = MechanicalExpenseEntry.objects.filter(
            record=record,
            expense__expense_type=ExpenseType.OVERHEAD,
            expense__is_active=True
        ).aggregate(
            total=Coalesce(Sum('amount_spent'), Decimal('0'))
        )['total']

        return (auto_total + mech_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    def _calculate_product_overhead_share(cls, product: Product) -> Decimal:
        """
        Расчёт доли накладных расходов для товара (для снапшота).

        Базируется на popularity_weight товара относительно всех активных товаров.
        """
        total_weight = Product.objects.filter(
            is_active=True
        ).aggregate(
            total=Coalesce(Sum('popularity_weight'), Decimal('1'))
        )['total']

        if total_weight <= 0:
            return Decimal('0')

        product_share = (product.popularity_weight or Decimal('1')) / total_weight

        # Общие месячные накладные / 30 * доля товара
        daily_overhead = Expense.objects.filter(
            expense_type=ExpenseType.OVERHEAD,
            is_active=True
        ).aggregate(
            total=Coalesce(
                Sum(F('monthly_amount') / Value(DAYS_IN_MONTH)),
                Decimal('0')
            )
        )['total']

        return (daily_overhead * product_share).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    def _calculate_product_revenue(cls, product: Product, days: int = 30) -> Decimal:
        """
        Расчёт выручки от товара за указанный период.

        Args:
            product: Товар
            days: Количество дней

        Returns:
            Выручка
        """
        from orders.models import StoreOrderItem

        start_date = timezone.now() - timezone.timedelta(days=days)

        revenue = StoreOrderItem.objects.filter(
            product=product,
            order__status='completed',
            order__created_at__gte=start_date,
            is_bonus=False
        ).aggregate(
            total=Coalesce(Sum('total'), Decimal('0'))
        )['total']

        return revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    def _mark_snapshot_outdated(cls, product: Product) -> None:
        """Пометить кеш себестоимости как устаревший."""
        ProductCostSnapshot.objects.filter(product=product).update(is_outdated=True)


# =============================================================================
# СЕРВИС: УПРАВЛЕНИЕ РЕЦЕПТАМИ
# =============================================================================

class RecipeService:
    """
    Сервис управления рецептами товаров.

    Реализует "котловой метод" расчёта пропорций:
    Вместо ввода 0.01 (50/5000), пользователь вводит:
    - 50 кг муки
    - на 5000 булочек

    Пропорция вычисляется автоматически.
    """

    @classmethod
    @transaction.atomic
    def create_recipe(
            cls,
            product: Product,
            expense: Expense,
            ingredient_amount: Decimal,
            output_quantity: Decimal
    ) -> Recipe:
        """
        Создать рецепт с автоматическим расчётом пропорции.

        Args:
            product: Товар
            expense: Ингредиент (Expense с expense_type='physical')
            ingredient_amount: Количество ингредиента (например, 50 кг)
            output_quantity: Количество продукции (например, 5000 шт)

        Returns:
            Созданный рецепт

        Raises:
            ValueError: Если expense не является ингредиентом
        """
        if expense.expense_type != ExpenseType.PHYSICAL:
            raise ValueError("Можно привязывать только физические расходы (ингредиенты)")

        recipe = Recipe.objects.create(
            product=product,
            expense=expense,
            ingredient_amount=ingredient_amount,
            output_quantity=output_quantity
        )

        # Пересчитываем себестоимость товара
        CostCalculator.update_product_cost_and_price(product)

        return recipe

    @classmethod
    @transaction.atomic
    def update_recipe(
            cls,
            recipe: Recipe,
            ingredient_amount: Optional[Decimal] = None,
            output_quantity: Optional[Decimal] = None
    ) -> Recipe:
        """
        Обновить рецепт.

        Args:
            recipe: Рецепт для обновления
            ingredient_amount: Новое количество ингредиента
            output_quantity: Новое количество продукции

        Returns:
            Обновлённый рецепт
        """
        if ingredient_amount is not None:
            recipe.ingredient_amount = ingredient_amount
        if output_quantity is not None:
            recipe.output_quantity = output_quantity

        recipe.save()

        # Пересчитываем себестоимость товара
        CostCalculator.update_product_cost_and_price(recipe.product)

        return recipe

    @classmethod
    @transaction.atomic
    def delete_recipe(cls, recipe: Recipe) -> None:
        """
        Удалить рецепт и пересчитать себестоимость.

        Args:
            recipe: Рецепт для удаления
        """
        product = recipe.product
        recipe.delete()

        # Пересчитываем себестоимость товара
        CostCalculator.update_product_cost_and_price(product)

    @classmethod
    def get_product_recipes(cls, product: Product) -> List[Dict]:
        """
        Получить все рецепты товара с рассчитанными данными.

        Args:
            product: Товар

        Returns:
            Список рецептов с данными о стоимости
        """
        recipes = product.recipes.select_related('expense').filter(
            expense__is_active=True
        )

        result = []
        for recipe in recipes:
            cost_per_unit = recipe.get_ingredient_cost_per_unit()
            result.append({
                'id': recipe.id,
                'expense_id': recipe.expense.id,
                'expense_name': recipe.expense.name,
                'expense_unit': recipe.expense.unit,
                'ingredient_amount': recipe.ingredient_amount,
                'output_quantity': recipe.output_quantity,
                'proportion': recipe.proportion,
                'price_per_unit': recipe.expense.price_per_unit,
                'cost_per_product_unit': cost_per_unit,
            })

        return result

    @classmethod
    @transaction.atomic
    def migrate_from_legacy(cls, product: Product) -> int:
        """
        Мигрировать данные из ProductExpenseRelation в Recipe.

        Args:
            product: Товар для миграции

        Returns:
            Количество созданных рецептов
        """
        count = 0

        for relation in product.expense_relations.filter(
                expense__expense_type=ExpenseType.PHYSICAL
        ):
            if relation.proportion > 0:
                # Предполагаем, что proportion — это расход на 1 единицу
                # Создаём рецепт с output_quantity=1
                Recipe.objects.get_or_create(
                    product=product,
                    expense=relation.expense,
                    defaults={
                        'ingredient_amount': relation.proportion,
                        'output_quantity': Decimal('1'),
                    }
                )
                count += 1

        return count


# =============================================================================
# СЕРВИС: БОНУСНАЯ СИСТЕМА
# =============================================================================

class BonusService:
    """
    Система бонусов: каждый 21-й товар бесплатно.

    Правила из ТЗ:
    - Бонусы применяются только к штучным товарам
    - Весовые товары НЕ участвуют в бонусах
    - Если админ вручную сделал товар бонусным — правило 21 не применяется
    - Бонусы считаются по количеству, не влияют на сумму дохода
    """

    @classmethod
    @transaction.atomic
    def add_products_to_counter(
            cls,
            store,
            partner,
            product: Product,
            quantity: int
    ) -> Tuple[int, int]:
        """
        Добавить товары в счётчик и рассчитать бонусы.

        Args:
            store: Магазин
            partner: Партнёр
            product: Товар
            quantity: Количество

        Returns:
            Tuple[новые_бонусы, всего_бонусов_доступно]
        """
        # Весовые товары не участвуют в бонусах
        if product.is_weight_based:
            return (0, 0)

        # Получаем или создаём счётчик
        counter, created = StoreProductCounter.objects.select_for_update().get_or_create(
            store=store,
            partner=partner,
            product=product,
            defaults={'total_count': 0, 'bonuses_given': 0}
        )

        # Предыдущее количество доступных бонусов
        prev_pending = counter.get_pending_bonus_count()

        # Увеличиваем счётчик
        counter.total_count += quantity
        counter.save(update_fields=['total_count', 'updated_at'])

        # Новое количество доступных бонусов
        new_pending = counter.get_pending_bonus_count()

        # Количество новых бонусов
        new_bonuses = new_pending - prev_pending

        return (new_bonuses, new_pending)

    @classmethod
    @transaction.atomic
    def apply_bonus_to_order(cls, order: 'StoreOrder') -> Decimal:
        """
        Применить бонусы к заказу магазина.

        Создаёт бонусные позиции в заказе для каждого товара,
        у которого есть невыданные бонусы.

        Args:
            order: Заказ магазина

        Returns:
            Общая стоимость применённых бонусов
        """
        from orders.models import StoreOrderItem

        bonus_total = Decimal('0')

        for item in order.items.filter(is_bonus=False):
            # Весовые товары не участвуют
            if item.product.is_weight_based:
                continue

            # Получаем счётчик
            counter = StoreProductCounter.objects.select_for_update().filter(
                store=order.store,
                partner=order.partner,
                product=item.product
            ).first()

            if not counter or not counter.has_pending_bonus():
                continue

            # Количество бонусов к выдаче
            bonus_qty = counter.get_pending_bonus_count()
            bonus_value = item.product.final_price * bonus_qty

            # Создаём бонусную позицию
            StoreOrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=bonus_qty,
                price=Decimal('0'),
                total=Decimal('0'),
                is_bonus=True
            )

            # Записываем в историю
            BonusHistory.objects.create(
                store=order.store,
                partner=order.partner,
                product=item.product,
                order=order,
                quantity=bonus_qty,
                bonus_value=bonus_value
            )

            # Обновляем счётчик
            counter.bonuses_given += bonus_qty
            counter.last_bonus_at = timezone.now()
            counter.save(update_fields=['bonuses_given', 'last_bonus_at', 'updated_at'])

            bonus_total += bonus_value

        return bonus_total

    @classmethod
    def get_bonus_status(
            cls,
            store,
            partner,
            product: Product
    ) -> Dict:
        """
        Получить статус бонуса для товара.

        Args:
            store: Магазин
            partner: Партнёр
            product: Товар

        Returns:
            Словарь со статусом бонуса
        """
        counter = StoreProductCounter.objects.filter(
            store=store,
            partner=partner,
            product=product
        ).first()

        if not counter:
            return {
                'total_count': 0,
                'bonuses_given': 0,
                'pending_bonuses': 0,
                'next_bonus_at': BONUS_THRESHOLD,
                'has_bonus': False,
                'last_bonus_at': None,
            }

        pending = counter.get_pending_bonus_count()
        progress = counter.total_count % BONUS_THRESHOLD

        return {
            'total_count': counter.total_count,
            'bonuses_given': counter.bonuses_given,
            'pending_bonuses': pending,
            'next_bonus_at': BONUS_THRESHOLD - progress if progress > 0 else BONUS_THRESHOLD,
            'has_bonus': pending > 0,
            'last_bonus_at': counter.last_bonus_at,
            'progress': progress,
            'progress_percent': round(progress / BONUS_THRESHOLD * 100, 1),
        }


# =============================================================================
# СЕРВИС: ЭКРАНЫ УЧЁТА (ДИНАМИЧНЫЙ / СТАТИЧНЫЙ)
# =============================================================================

class AccountingService:
    """
    Сервис для экранов "Динамичный учёт" и "Статичный учёт".

    Соответствует дизайну:
    - Динамичный: ингредиенты + таблица товаров с себестоимостью
    - Статичный: аренда, свет, налоги — фиксированные суммы
    """

    @classmethod
    def get_dynamic_expenses(cls) -> List[Expense]:
        """
        Получить расходы для экрана "Динамичный учёт".

        Возвращает физические расходы (ингредиенты).
        """
        return list(
            Expense.objects
            .filter(
                accounting_mode=AccountingMode.DYNAMIC,
                is_active=True
            )
            .order_by('name')
        )

    @classmethod
    def get_static_expenses(cls) -> List[Expense]:
        """
        Получить расходы для экрана "Статичный учёт".

        Возвращает накладные расходы (аренда, зарплата и т.д.).
        """
        return list(
            Expense.objects
            .filter(
                accounting_mode=AccountingMode.STATIC,
                is_active=True
            )
            .order_by('name')
        )

    @classmethod
    def get_cost_table_data(cls) -> List[Dict]:
        """
        Получить данные для таблицы себестоимости.

        Соответствует экрану "Динамичный учёт" → Секция "Товары":
        | Название | Наценка | Себ-сть | Расход | Доход |

        Returns:
            Список словарей с данными о товарах
        """
        # Обновляем устаревшие снапшоты
        CostCalculator.bulk_update_snapshots()

        # Получаем данные из снапшотов
        snapshots = ProductCostSnapshot.objects.select_related('product').filter(
            product__is_active=True
        ).order_by('product__name')

        result = []
        for snapshot in snapshots:
            result.append({
                'product_id': snapshot.product.id,
                'name': snapshot.product.name,
                'markup': snapshot.markup_amount,
                'cost_price': snapshot.cost_price,
                'expense': snapshot.total_expense,
                'revenue': snapshot.revenue,
                'profit': snapshot.profit,
                'is_weight_based': snapshot.product.is_weight_based,
            })

        return result

    @classmethod
    @transaction.atomic
    def update_static_expense(cls, expense: Expense, monthly_amount: Decimal) -> Expense:
        """
        Обновить сумму статичного расхода.

        Args:
            expense: Расход для обновления
            monthly_amount: Новая месячная сумма

        Returns:
            Обновлённый расход
        """
        expense.monthly_amount = monthly_amount
        expense.save(update_fields=['monthly_amount', 'updated_at'])

        # Помечаем все снапшоты как устаревшие
        ProductCostSnapshot.objects.all().update(is_outdated=True)

        return expense
