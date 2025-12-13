# apps/products/services.py
"""Сервисы для products."""

from decimal import Decimal
from datetime import date
from typing import List, Dict, Any, Optional
from django.db import transaction
from django.db.models import Sum, Avg, Q

from .models import (
    Expense,
    Product,
    ProductionBatch,
    ProductImage,
    ProductExpenseRelation,
    ExpenseStatus,
    ExpenseState
)
from dataclasses import dataclass


@dataclass
class ExpenseCalculationResult:
    """Результат расчёта расходов с иерархией."""

    # Расходы по категориям
    suzerains_total: Decimal  # Все Сюзерены (с их Вассалами)
    civilians_total: Decimal  # Все Обыватели
    total_expenses: Decimal  # Общая сумма

    # Детализация
    daily_expenses: Decimal  # Дневные расходы
    monthly_expenses: Decimal  # Месячные расходы
    monthly_per_day: Decimal  # Месячные / 30

    # Breakdown по группам
    breakdown: Dict[str, List[Dict]]  # Детальная информация


@dataclass
class ProductCostData:
    """Данные для расчёта себестоимости товара."""

    product: Product
    quantity_produced: Decimal  # Количество произведённого товара

    # Расходы
    total_expenses: Decimal
    daily_expenses: Decimal
    monthly_expenses_per_day: Decimal

    # Результаты
    cost_per_unit: Decimal  # Себестоимость за единицу
    markup_percentage: Decimal  # Наценка %
    final_price: Decimal  # Цена продажи
    profit_per_unit: Decimal


class ExpenseService:
    """
    Сервис для работы с расходами с учётом иерархии.

    КРИТИЧЕСКИЕ МЕТОДЫ:
    - calculate_total_expenses_with_hierarchy() - расчёт с Сюзеренами/Вассалами
    - recalculate_vassals() - пересчёт всех Вассалов
    - get_expense_breakdown() - детальная разбивка
    """

    @classmethod
    def calculate_total_expenses_with_hierarchy(
            cls,
            date: Optional['date'] = None,
            expense_type: Optional[str] = None,
    ) -> ExpenseCalculationResult:
        """
        Рассчитать общие расходы с учётом иерархии Сюзерен → Вассал.

        АЛГОРИТМ:
        1. Собрать всех Сюзеренов
        2. Для каждого Сюзерена рассчитать его расходы + расходы его Вассалов
        3. Собрать всех Обывателей
        4. Суммировать всё

        Args:
            date: Дата для фильтрации (опционально)
            expense_type: Тип расхода (physical/overhead, опционально)

        Returns:
            ExpenseCalculationResult с детализацией
        """
        # Фильтр активных расходов
        expenses_qs = Expense.objects.filter(is_active=True)

        if expense_type:
            expenses_qs = expenses_qs.filter(expense_type=expense_type)

        # =====================================================================
        # 1. СЮЗЕРЕНЫ (с их Вассалами)
        # =====================================================================
        suzerains = expenses_qs.filter(expense_status=ExpenseStatus.SUZERAIN)

        suzerains_total = Decimal('0')
        suzerains_breakdown = []

        for suzerain in suzerains:
            # Расходы самого Сюзерена
            suzerain_amount = suzerain.calculate_amount()

            # Расходы его Вассалов
            vassals_total = Decimal('0')
            vassals_list = []

            for vassal in suzerain.vassals.filter(is_active=True):
                vassal_amount = vassal.calculate_amount()
                vassals_total += vassal_amount

                vassals_list.append({
                    'id': vassal.id,
                    'name': vassal.name,
                    'quantity': float(vassal.calculate_vassal_quantity()),
                    'unit_cost': float(vassal.unit_cost),
                    'amount': float(vassal_amount),
                    'dependency_ratio': float(vassal.dependency_ratio or 0),
                })

            # Общая сумма группы
            group_total = suzerain_amount + vassals_total
            suzerains_total += group_total

            suzerains_breakdown.append({
                'id': suzerain.id,
                'name': suzerain.name,
                'quantity': float(suzerain.quantity),
                'unit_cost': float(suzerain.unit_cost),
                'suzerain_amount': float(suzerain_amount),
                'vassals': vassals_list,
                'vassals_total': float(vassals_total),
                'group_total': float(group_total),
            })

        # =====================================================================
        # 2. ОБЫВАТЕЛИ (независимые расходы)
        # =====================================================================
        civilians = expenses_qs.filter(expense_status=ExpenseStatus.CIVILIAN)

        civilians_total = Decimal('0')
        civilians_breakdown = []

        for civilian in civilians:
            amount = civilian.calculate_amount()
            civilians_total += amount

            civilians_breakdown.append({
                'id': civilian.id,
                'name': civilian.name,
                'expense_type': civilian.get_expense_type_display(),
                'daily_amount': float(civilian.daily_amount),
                'monthly_amount': float(civilian.monthly_amount),
                'amount': float(amount),
            })

        # =====================================================================
        # 3. ОБЩИЕ СУММЫ
        # =====================================================================
        total_expenses = suzerains_total + civilians_total

        # Разделение на дневные и месячные
        daily_expenses = Decimal('0')
        monthly_expenses = Decimal('0')

        for expense in expenses_qs:
            # Для Вассалов используем рассчитанную сумму
            if expense.expense_status == ExpenseStatus.VASSAL:
                # Вассалы уже учтены в Сюзеренах, пропускаем
                continue

            daily_expenses += expense.daily_amount
            monthly_expenses += expense.monthly_amount

        # Месячные расходы в пересчёте на день
        monthly_per_day = (monthly_expenses / 30).quantize(Decimal('0.01'))

        # Результат
        return ExpenseCalculationResult(
            suzerains_total=suzerains_total,
            civilians_total=civilians_total,
            total_expenses=total_expenses,
            daily_expenses=daily_expenses,
            monthly_expenses=monthly_expenses,
            monthly_per_day=monthly_per_day,
            breakdown={
                'suzerains': suzerains_breakdown,
                'civilians': civilians_breakdown,
            }
        )

    @classmethod
    @transaction.atomic
    def recalculate_vassals(cls, suzerain: Expense) -> int:
        """
        Пересчитать всех Вассалов, зависящих от Сюзерена.

        Используется когда:
        - Изменилось количество у Сюзерена
        - Нужно вручную обновить зависимости

        Args:
            suzerain: Расход со статусом SUZERAIN

        Returns:
            int: Количество пересчитанных Вассалов
        """
        if suzerain.expense_status != ExpenseStatus.SUZERAIN:
            return 0

        count = 0

        for vassal in suzerain.vassals.filter(
                is_active=True,
                expense_state=ExpenseState.AUTOMATIC
        ):
            # Пересчитываем количество
            vassal.quantity = vassal.calculate_vassal_quantity()
            vassal.save(update_fields=['quantity'])
            count += 1

        return count

    @classmethod
    def get_expense_breakdown(
            cls,
            expense_type: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Получить детальную разбивку расходов.

        Возвращает:
        - Группировку по Сюзеренам
        - Обывателей отдельно
        - Общие суммы

        Args:
            expense_type: Тип расхода (опционально)

        Returns:
            Dict с детальной информацией
        """
        result = cls.calculate_total_expenses_with_hierarchy(
            expense_type=expense_type
        )

        return {
            'summary': {
                'suzerains_total': float(result.suzerains_total),
                'civilians_total': float(result.civilians_total),
                'total_expenses': float(result.total_expenses),
                'daily_expenses': float(result.daily_expenses),
                'monthly_expenses': float(result.monthly_expenses),
                'monthly_per_day': float(result.monthly_per_day),
            },
            'breakdown': result.breakdown,
        }

    @classmethod
    def calculate_product_cost(
            cls,
            product: Product,
            quantity_produced: Decimal,
    ) -> ProductCostData:
        """
        Рассчитать себестоимость товара с учётом расходов.

        ФОРМУЛА:
        1. Собрать все расходы (с иерархией)
        2. Поделить на количество произведённого товара
        3. Применить наценку

        Args:
            product: Товар
            quantity_produced: Количество произведённого товара

        Returns:
            ProductCostData с детальным расчётом
        """
        # Получаем расходы с иерархией
        expenses_result = cls.calculate_total_expenses_with_hierarchy()

        # Расчёт себестоимости за единицу
        if quantity_produced > 0:
            cost_per_unit = (
                    expenses_result.total_expenses / quantity_produced
            ).quantize(Decimal('0.01'))
        else:
            cost_per_unit = Decimal('0')

        # Применяем наценку
        markup_percentage = product.markup_percentage or Decimal('0')
        markup_multiplier = Decimal('1') + (markup_percentage / 100)
        final_price = (cost_per_unit * markup_multiplier).quantize(Decimal('0.01'))

        # Прибыль с единицы
        profit_per_unit = final_price - cost_per_unit

        return ProductCostData(
            product=product,
            quantity_produced=quantity_produced,
            total_expenses=expenses_result.total_expenses,
            daily_expenses=expenses_result.daily_expenses,
            monthly_expenses_per_day=expenses_result.monthly_per_day,
            cost_per_unit=cost_per_unit,
            markup_percentage=markup_percentage,
            final_price=final_price,
            profit_per_unit=profit_per_unit,
        )


class ProductionService:
    """Сервис производства."""

    @classmethod
    @transaction.atomic
    def create_production_batch(
            cls,
            product_id: int,
            date_obj: date,
            quantity_produced: Decimal,
            notes: str = ''
    ) -> ProductionBatch:
        """
        Создать производственную запись.

        Args:
            product_id: ID товара
            date_obj: Дата производства
            quantity_produced: Произведено единиц
            notes: Заметки
        """
        product = Product.objects.get(pk=product_id)

        # Получаем расходы
        expenses = ExpenseService.get_total_expenses_for_date(date_obj)

        # Создаём запись
        batch = ProductionBatch.objects.create(
            product=product,
            date=date_obj,
            quantity_produced=quantity_produced,
            total_daily_expenses=expenses['daily'],
            total_monthly_expenses_per_day=expenses['monthly_per_day'],
            notes=notes
        )

        return batch

    @classmethod
    def get_production_history(
            cls,
            product_id: int = None,
            limit: int = 30
    ) -> List[ProductionBatch]:
        """Получить историю производства."""
        queryset = ProductionBatch.objects.all()

        if product_id:
            queryset = queryset.filter(product_id=product_id)

        return queryset.order_by('-date')[:limit]

    @classmethod
    def get_production_stats(cls, product_id: int) -> Dict[str, Any]:
        """Статистика производства товара."""
        from django.db.models import Min, Max, Count

        stats = ProductionBatch.objects.filter(
            product_id=product_id
        ).aggregate(
            avg_cost=Avg('cost_price_calculated'),
            min_cost=Min('cost_price_calculated'),
            max_cost=Max('cost_price_calculated'),
            total_qty=Sum('quantity_produced'),
            count=Count('id')
        )

        return {
            'avg_cost_price': stats['avg_cost'] or Decimal('0'),
            'min_cost_price': stats['min_cost'] or Decimal('0'),
            'max_cost_price': stats['max_cost'] or Decimal('0'),
            'total_produced': stats['total_qty'] or Decimal('0'),
            'batches_count': stats['count'] or 0
        }


class ProductService:
    """Сервис товаров."""

    @classmethod
    def get_catalog_for_stores(cls) -> List[Dict[str, Any]]:
        """
        Каталог для магазинов.

        Магазины видят только final_price!
        """
        products = Product.objects.filter(
            is_active=True,
            is_available=True
        ).prefetch_related('images')

        catalog = []
        for product in products:
            main_image = product.images.filter(order=0).first()

            catalog.append({
                'id': product.id,
                'name': product.name,
                'description': product.description,
                'unit': product.unit,
                'is_weight_based': product.is_weight_based,
                'is_bonus': product.is_bonus,
                'final_price': float(product.final_price),
                'price_per_100g': float(product.price_per_100g) if product.is_weight_based else None,
                'stock_quantity': float(product.stock_quantity),
                'main_image': main_image.image.url if main_image else None,
                'images_count': product.images.count()
            })

        return catalog

    @classmethod
    def get_product_details(cls, product_id: int, for_admin: bool = False) -> Dict[str, Any]:
        """
        Детали товара.

        Args:
            product_id: ID товара
            for_admin: True - показать все данные, False - только для просмотра
        """
        product = Product.objects.get(pk=product_id)

        data = {
            'id': product.id,
            'name': product.name,
            'description': product.description,
            'unit': product.unit,
            'is_weight_based': product.is_weight_based,
            'is_bonus': product.is_bonus,
            'final_price': float(product.final_price),
            'stock_quantity': float(product.stock_quantity),
            'is_active': product.is_active,
            'is_available': product.is_available,
        }

        if for_admin:
            # Для админа - полная информация
            prod_stats = ProductionService.get_production_stats(product_id)

            data.update({
                'average_cost_price': float(product.average_cost_price),
                'markup_percentage': float(product.markup_percentage),
                'profit_per_unit': float(product.profit_per_unit),
                'popularity_weight': float(product.popularity_weight),
                'production_stats': prod_stats,
            })

        # Изображения
        data['images'] = [
            {
                'id': img.id,
                'url': img.image.url,
                'order': img.order
            }
            for img in product.images.all()
        ]

        return data

    @classmethod
    @transaction.atomic
    def update_markup(
            cls,
            product_id: int,
            markup_percentage: Decimal
    ) -> Product:
        """Обновить наценку товара."""
        product = Product.objects.get(pk=product_id)
        product.markup_percentage = markup_percentage
        product.save()  # Автоматически пересчитает final_price
        return product


    @classmethod
    def calculate_cost_and_price(
            cls,
            product_id: int,
            quantity_produced: Decimal,
    ) -> Dict[str, Any]:
        # ✅ ИСПОЛЬЗУЕМ ExpenseService вместо простого Sum

        product = Product.objects.get(pk=product_id)

        # Рассчитываем с учётом иерархии
        cost_data = ExpenseService.calculate_product_cost(
            product=product,
            quantity_produced=quantity_produced
        )

        # Обновляем товар
        product.average_cost_price = cost_data.cost_per_unit
        product.final_price = cost_data.final_price
        product.save(update_fields=['average_cost_price', 'final_price'])

        return {
            'product_id': product.id,
            'quantity_produced': float(quantity_produced),
            'expenses': {
                'total': float(cost_data.total_expenses),
                'daily': float(cost_data.daily_expenses),
                'monthly_per_day': float(cost_data.monthly_expenses_per_day),
            },
            'cost_per_unit': float(cost_data.cost_per_unit),
            'markup_percentage': float(cost_data.markup_percentage),
            'final_price': float(cost_data.final_price),
            'profit_per_unit': float(cost_data.profit_per_unit),
        }


class ProductImageService:
    """Сервис изображений."""

    @classmethod
    @transaction.atomic
    def add_images(
            cls,
            product_id: int,
            images: List[Any]
    ) -> List[ProductImage]:
        """Добавить изображения (до 3 штук)."""
        product = Product.objects.get(pk=product_id)
        existing = product.images.count()

        if existing + len(images) > 3:
            raise ValueError(
                f'Максимум 3 изображения. Сейчас: {existing}'
            )

        created = []
        for i, image_file in enumerate(images):
            img = ProductImage.objects.create(
                product=product,
                image=image_file,
                order=existing + i
            )
            created.append(img)

        return created

    @classmethod
    @transaction.atomic
    def delete_image(cls, image_id: int) -> None:
        """Удалить изображение и переупорядочить."""
        from django.db.models import F

        image = ProductImage.objects.get(pk=image_id)
        deleted_order = image.order
        product_id = image.product_id

        image.delete()

        # Переупорядочить
        ProductImage.objects.filter(
            product_id=product_id,
            order__gt=deleted_order
        ).update(order=F('order') - 1)

    @classmethod
    @transaction.atomic
    def reorder_images(
            cls,
            product_id: int,
            new_order: List[int]
    ) -> None:
        """Изменить порядок изображений."""
        for i, image_id in enumerate(new_order):
            ProductImage.objects.filter(
                id=image_id,
                product_id=product_id
            ).update(order=i)