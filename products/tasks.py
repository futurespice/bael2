# apps/products/tasks.py
"""
Celery задачи для товаров (v3.0).

ТЗ Бахрам акя:
- Пересчёт себестоимости раз в 1.5 недели на основе ПРОДАЖ
- Распределение накладных по объёму продаж
- Учёт сезонности (товары продаются по-разному в разные сезоны)
"""

import logging
from decimal import Decimal
from datetime import date, timedelta
from celery import shared_task

logger = logging.getLogger(__name__)

# Период анализа продаж (1.5 недели = 11 дней)
SALES_ANALYSIS_PERIOD_DAYS = 11


@shared_task
def recalculate_product_costs():
    """
    Пересчитать себестоимость всех товаров (старая версия).

    Запускается периодически для актуализации цен.
    """
    from .models import Product

    products = Product.objects.filter(is_active=True)
    updated = 0

    for product in products:
        try:
            product.update_average_cost_price()
            updated += 1
        except Exception as e:
            logger.error(f"Ошибка пересчёта себестоимости {product.name}: {e}")

    logger.info(f"Пересчитана себестоимость {updated} товаров")
    return {'updated': updated}


@shared_task
def recalculate_costs_by_sales():
    """
    Пересчитать себестоимость на основе ПРОДАЖ (ТЗ Бахрам акя).

    Запускается раз в 1.5 недели (11 дней).

    Что делает:
    1. Анализирует продажи за последние 11 дней
    2. Рассчитывает долю каждого товара в общих продажах
    3. Распределяет накладные пропорционально продажам
    4. Обновляет popularity_weight (коэффициент популярности)
    5. Пересчитывает среднюю себестоимость

    Пример:
    - Пельмени зелёные продаются 1000 шт/неделю → 90% накладных
    - Пельмени красные продаются 100 шт/неделю → 10% накладных
    """
    from django.db.models import Sum
    from orders.models import StoreOrderItem, StoreOrderStatus
    from .models import Product, Expense, ExpenseType, ProductRecipe, ExpenseStatus
    from .services import OverheadDistributor

    today = date.today()
    start_date = today - timedelta(days=SALES_ANALYSIS_PERIOD_DAYS)

    logger.info(f"Пересчёт себестоимости за период {start_date} - {today}")

    # =========================================================================
    # 1. ПОЛУЧАЕМ СТАТИСТИКУ ПРОДАЖ
    # =========================================================================

    sales_data = StoreOrderItem.objects.filter(
        order__created_at__date__gte=start_date,
        order__created_at__date__lte=today,
        order__status=StoreOrderStatus.ACCEPTED,
        is_bonus=False
    ).values('product_id').annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total')
    )

    # Преобразуем в словарь
    sales_by_product = {
        item['product_id']: {
            'quantity': item['total_quantity'] or Decimal('0'),
            'revenue': item['total_revenue'] or Decimal('0')
        }
        for item in sales_data
    }

    total_sales_quantity = sum(s['quantity'] for s in sales_by_product.values())
    total_sales_revenue = sum(s['revenue'] for s in sales_by_product.values())

    logger.info(f"Продажи за период: {total_sales_quantity} единиц на сумму {total_sales_revenue}")

    if total_sales_quantity == 0:
        logger.warning("Нет продаж за период, пропускаем пересчёт")
        return {'updated': 0, 'reason': 'no_sales'}

    # =========================================================================
    # 2. ПОЛУЧАЕМ НАКЛАДНЫЕ РАСХОДЫ
    # =========================================================================

    total_overhead = Decimal('0')
    overhead_expenses = Expense.objects.filter(
        expense_type=ExpenseType.OVERHEAD,
        is_active=True
    )

    for expense in overhead_expenses:
        # Накладные за период (не за день)
        daily_amount = expense.calculate_amount()
        total_overhead += daily_amount * SALES_ANALYSIS_PERIOD_DAYS

    logger.info(f"Накладные расходы за период: {total_overhead}")

    # =========================================================================
    # 3. ОБНОВЛЯЕМ КАЖДЫЙ ТОВАР
    # =========================================================================

    products = Product.objects.filter(is_active=True)
    updated = 0
    results = []

    for product in products:
        try:
            product_sales = sales_by_product.get(product.id, {
                'quantity': Decimal('0'),
                'revenue': Decimal('0')
            })

            sales_quantity = product_sales['quantity']
            sales_revenue = product_sales['revenue']

            # Доля в продажах
            if total_sales_quantity > 0:
                sales_share = sales_quantity / total_sales_quantity
            else:
                sales_share = Decimal('0')

            # Накладные для этого товара
            product_overhead = (total_overhead * sales_share).quantize(Decimal('0.01'))

            # =====================================================
            # РАССЧИТЫВАЕМ ФИЗИЧЕСКИЕ РАСХОДЫ
            # =====================================================

            total_physical = Decimal('0')

            # Получаем рецепт товара
            suzerain_recipe = ProductRecipe.objects.filter(
                product=product,
                expense__expense_status=ExpenseStatus.SUZERAIN
            ).select_related('expense').first()

            if suzerain_recipe and sales_quantity > 0:
                # Объём сюзерена = количество × норма на единицу
                suzerain_volume = sales_quantity * suzerain_recipe.quantity_per_unit
                suzerain_cost = suzerain_volume * (suzerain_recipe.expense.price_per_unit or Decimal('0'))
                total_physical += suzerain_cost

                # Остальные физические расходы (пропорции от сюзерена)
                other_recipes = ProductRecipe.objects.filter(
                    product=product,
                    expense__expense_type=ExpenseType.PHYSICAL
                ).exclude(
                    expense__expense_status=ExpenseStatus.SUZERAIN
                ).select_related('expense')

                for recipe in other_recipes:
                    if recipe.proportion:
                        item_volume = suzerain_volume * recipe.proportion
                        item_cost = item_volume * (recipe.expense.price_per_unit or Decimal('0'))
                        total_physical += item_cost

            # =====================================================
            # ИТОГОВАЯ СЕБЕСТОИМОСТЬ
            # =====================================================

            total_cost = total_physical + product_overhead

            if sales_quantity > 0:
                cost_per_unit = (total_cost / sales_quantity).quantize(Decimal('0.01'))
            else:
                # Для товаров без продаж используем старую себестоимость
                cost_per_unit = product.average_cost_price or Decimal('0')

            # Обновляем товар
            old_cost = product.average_cost_price
            product.average_cost_price = cost_per_unit
            product.popularity_weight = sales_share * 100  # В процентах
            product.save(update_fields=['average_cost_price', 'popularity_weight', 'updated_at'])

            updated += 1

            results.append({
                'product': product.name,
                'old_cost': float(old_cost or 0),
                'new_cost': float(cost_per_unit),
                'sales_quantity': float(sales_quantity),
                'sales_share': float(sales_share * 100),
                'overhead_share': float(product_overhead)
            })

            logger.info(
                f"Товар {product.name}: "
                f"себестоимость {old_cost} → {cost_per_unit}, "
                f"продажи {sales_quantity}, "
                f"доля {sales_share:.1%}"
            )

        except Exception as e:
            logger.error(f"Ошибка пересчёта {product.name}: {e}")

    logger.info(f"Пересчитана себестоимость {updated} товаров")

    return {
        'updated': updated,
        'period_days': SALES_ANALYSIS_PERIOD_DAYS,
        'total_sales': float(total_sales_quantity),
        'total_overhead': float(total_overhead),
        'products': results
    }


@shared_task
def update_product_popularity():
    """
    Обновить коэффициенты популярности товаров.

    Запускается еженедельно для учёта сезонности.
    """
    from django.db.models import Sum
    from orders.models import StoreOrderItem, StoreOrderStatus
    from .models import Product

    today = date.today()
    start_date = today - timedelta(days=7)

    # Получаем продажи за неделю
    sales = StoreOrderItem.objects.filter(
        order__created_at__date__gte=start_date,
        order__status=StoreOrderStatus.ACCEPTED,
        is_bonus=False
    ).values('product_id').annotate(
        total_quantity=Sum('quantity')
    )

    sales_dict = {s['product_id']: s['total_quantity'] for s in sales}
    total_sales = sum(sales_dict.values()) or Decimal('1')

    updated = 0
    for product in Product.objects.filter(is_active=True):
        product_sales = sales_dict.get(product.id, Decimal('0'))
        popularity = (product_sales / total_sales * 100).quantize(Decimal('0.01'))

        product.popularity_weight = popularity
        product.save(update_fields=['popularity_weight', 'updated_at'])
        updated += 1

    logger.info(f"Обновлена популярность {updated} товаров")
    return {'updated': updated}


@shared_task
def cleanup_inactive_products():
    """
    Деактивировать товары без остатков более 30 дней.
    """
    from datetime import timedelta
    from decimal import Decimal
    from django.utils import timezone
    from .models import Product
    
    threshold = timezone.now() - timedelta(days=30)
    
    # Товары без остатков и без продаж за 30 дней
    inactive = Product.objects.filter(
        stock_quantity__lte=Decimal('0'),
        updated_at__lt=threshold,
        is_active=True
    )
    
    count = inactive.update(is_available=False)
    
    logger.info(f"Деактивировано {count} товаров без остатков")
    return {'deactivated': count}
