# apps/products/tasks.py
"""
Celery-задачи для модуля products.

Фоновые задачи:
- Пересчёт себестоимости товаров
- Обновление кеша (ProductCostSnapshot)
- Обновление популярности товаров
- Миграция legacy данных
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def recalculate_product_cost(self, product_id: int) -> dict:
    """
    Пересчитать себестоимость одного товара.

    Args:
        product_id: ID товара

    Returns:
        Результат расчёта
    """
    from .models import Product
    from .services import CostCalculator

    try:
        product = Product.objects.get(id=product_id)

        with transaction.atomic():
            product = CostCalculator.update_product_cost_and_price(product)
            CostCalculator.update_product_snapshot(product)

        logger.info(
            f"Пересчитана себестоимость товара {product.name}: "
            f"cost_price={product.cost_price}, final_price={product.final_price}"
        )

        return {
            'status': 'success',
            'product_id': product_id,
            'cost_price': str(product.cost_price),
            'final_price': str(product.final_price),
        }

    except Product.DoesNotExist:
        logger.error(f"Товар с ID {product_id} не найден")
        return {
            'status': 'error',
            'product_id': product_id,
            'error': 'Product not found'
        }
    except Exception as exc:
        logger.exception(f"Ошибка пересчёта себестоимости товара {product_id}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def recalculate_all_products_cost(self) -> dict:
    """
    Пересчитать себестоимость всех активных товаров.

    Запускать при:
    - Изменении цен ингредиентов
    - Массовом обновлении рецептов
    - Ежедневно по расписанию

    Returns:
        Статистика выполнения
    """
    from .models import Product
    from .services import CostCalculator

    try:
        products = Product.objects.filter(is_active=True)
        total = products.count()
        updated = 0
        errors = 0

        for product in products.iterator():
            try:
                with transaction.atomic():
                    CostCalculator.update_product_cost_and_price(product)
                    CostCalculator.update_product_snapshot(product)
                updated += 1
            except Exception as e:
                logger.error(f"Ошибка пересчёта товара {product.id}: {e}")
                errors += 1

        logger.info(
            f"Пересчёт себестоимости завершён: "
            f"total={total}, updated={updated}, errors={errors}"
        )

        return {
            'status': 'success',
            'total': total,
            'updated': updated,
            'errors': errors,
        }

    except Exception as exc:
        logger.exception("Критическая ошибка пересчёта себестоимости")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def update_cost_snapshots(self, product_ids: Optional[List[int]] = None) -> dict:
    """
    Обновить кеш себестоимости (ProductCostSnapshot).

    Args:
        product_ids: Список ID товаров (или None для всех устаревших)

    Returns:
        Статистика выполнения
    """
    from .models import Product, ProductCostSnapshot
    from .services import CostCalculator

    try:
        if product_ids:
            products = list(Product.objects.filter(id__in=product_ids, is_active=True))
        else:
            products = None  # bulk_update_snapshots сама найдёт устаревшие

        count = CostCalculator.bulk_update_snapshots(products)

        logger.info(f"Обновлено {count} снапшотов себестоимости")

        return {
            'status': 'success',
            'updated_count': count,
        }

    except Exception as exc:
        logger.exception("Ошибка обновления снапшотов")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def update_product_popularity(self, product_id: int) -> dict:
    """
    Обновить коэффициент популярности товара.

    Популярность влияет на распределение накладных расходов
    (умная наценка по ТЗ 4.1.4).

    Args:
        product_id: ID товара

    Returns:
        Результат обновления
    """
    from .models import Product

    try:
        product = Product.objects.get(id=product_id)

        with transaction.atomic():
            product.update_popularity_weight()

        logger.info(
            f"Обновлена популярность товара {product.name}: "
            f"weight={product.popularity_weight}"
        )

        return {
            'status': 'success',
            'product_id': product_id,
            'popularity_weight': str(product.popularity_weight),
        }

    except Product.DoesNotExist:
        logger.error(f"Товар с ID {product_id} не найден")
        return {
            'status': 'error',
            'product_id': product_id,
            'error': 'Product not found'
        }
    except Exception as exc:
        logger.exception(f"Ошибка обновления популярности товара {product_id}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def update_all_products_popularity(self) -> dict:
    """
    Обновить популярность всех товаров.

    Рекомендуется запускать ежедневно.

    Returns:
        Статистика выполнения
    """
    from .models import Product

    try:
        products = Product.objects.filter(is_active=True)
        total = products.count()
        updated = 0

        for product in products.iterator():
            try:
                with transaction.atomic():
                    product.update_popularity_weight()
                updated += 1
            except Exception as e:
                logger.error(f"Ошибка обновления популярности товара {product.id}: {e}")

        logger.info(
            f"Обновление популярности завершено: total={total}, updated={updated}"
        )

        return {
            'status': 'success',
            'total': total,
            'updated': updated,
        }

    except Exception as exc:
        logger.exception("Критическая ошибка обновления популярности")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=1)
def migrate_legacy_recipes(self, product_id: Optional[int] = None) -> dict:
    """
    Мигрировать данные из ProductExpenseRelation в Recipe.

    Args:
        product_id: ID конкретного товара (или None для всех)

    Returns:
        Статистика миграции
    """
    from .models import Product
    from .services import RecipeService

    try:
        if product_id:
            products = Product.objects.filter(id=product_id)
        else:
            products = Product.objects.filter(is_active=True)

        total_products = products.count()
        total_recipes = 0

        for product in products.iterator():
            with transaction.atomic():
                count = RecipeService.migrate_from_legacy(product)
                total_recipes += count

        logger.info(
            f"Миграция рецептов завершена: "
            f"products={total_products}, recipes_created={total_recipes}"
        )

        return {
            'status': 'success',
            'products_processed': total_products,
            'recipes_created': total_recipes,
        }

    except Exception as exc:
        logger.exception("Ошибка миграции рецептов")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def recalculate_production_record(self, record_id: int) -> dict:
    """
    Пересчитать себестоимость всех позиций в записи производства.

    Args:
        record_id: ID записи производства

    Returns:
        Результат пересчёта
    """
    from .models import ProductionRecord
    from .services import CostCalculator

    try:
        record = ProductionRecord.objects.get(id=record_id)

        with transaction.atomic():
            items = CostCalculator.recalculate_all_items(record)

        total_cost = sum(item.total_cost or Decimal('0') for item in items)
        net_profit = sum(item.net_profit or Decimal('0') for item in items)

        logger.info(
            f"Пересчитана запись производства {record_id}: "
            f"items={len(items)}, total_cost={total_cost}, net_profit={net_profit}"
        )

        return {
            'status': 'success',
            'record_id': record_id,
            'items_count': len(items),
            'total_cost': str(total_cost),
            'net_profit': str(net_profit),
        }

    except ProductionRecord.DoesNotExist:
        logger.error(f"Запись производства {record_id} не найдена")
        return {
            'status': 'error',
            'record_id': record_id,
            'error': 'Record not found'
        }
    except Exception as exc:
        logger.exception(f"Ошибка пересчёта записи производства {record_id}")
        raise self.retry(exc=exc)


@shared_task
def mark_snapshots_outdated_for_expense(expense_id: int) -> dict:
    """
    Пометить снапшоты как устаревшие при изменении расхода.

    Вызывается сигналом при сохранении Expense.

    Args:
        expense_id: ID изменённого расхода
    """
    from .models import ProductCostSnapshot, Recipe, ProductExpenseRelation

    # Находим товары, использующие этот расход
    product_ids_from_recipes = Recipe.objects.filter(
        expense_id=expense_id
    ).values_list('product_id', flat=True)

    product_ids_from_relations = ProductExpenseRelation.objects.filter(
        expense_id=expense_id
    ).values_list('product_id', flat=True)

    all_product_ids = set(product_ids_from_recipes) | set(product_ids_from_relations)

    if all_product_ids:
        updated = ProductCostSnapshot.objects.filter(
            product_id__in=all_product_ids
        ).update(is_outdated=True)

        logger.info(
            f"Помечено {updated} снапшотов как устаревшие "
            f"из-за изменения расхода {expense_id}"
        )

        return {
            'status': 'success',
            'expense_id': expense_id,
            'snapshots_marked': updated,
        }

    return {
        'status': 'success',
        'expense_id': expense_id,
        'snapshots_marked': 0,
    }
