# apps/products/signals.py
"""
Django signals для модуля products.

Автоматические действия при изменениях:
- Пересчёт себестоимости при изменении рецептов
- Обновление снапшотов при изменении расходов
- Инвалидация кеша при изменении цен
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver

from .models import (
    Expense,
    Recipe,
    ProductExpenseRelation,
    ProductCostSnapshot,
)

logger = logging.getLogger(__name__)


# =============================================================================
# EXPENSE SIGNALS
# =============================================================================

@receiver(post_save, sender=Expense)
def on_expense_saved(sender, instance: Expense, created: bool, **kwargs):
    """
    При сохранении расхода — помечаем связанные снапшоты как устаревшие.
    """
    if created:
        # Новый расход — пока нет связанных товаров
        return

    # Запускаем Celery-таску для пометки снапшотов
    try:
        from .tasks import mark_snapshots_outdated_for_expense
        mark_snapshots_outdated_for_expense.delay(instance.id)
    except Exception as e:
        # Если Celery недоступен — выполняем синхронно
        logger.warning(f"Celery недоступен, выполняем синхронно: {e}")
        _mark_snapshots_for_expense(instance.id)


def _mark_snapshots_for_expense(expense_id: int):
    """Синхронная пометка снапшотов как устаревших."""
    from .models import ProductCostSnapshot, Recipe, ProductExpenseRelation

    product_ids_from_recipes = Recipe.objects.filter(
        expense_id=expense_id
    ).values_list('product_id', flat=True)

    product_ids_from_relations = ProductExpenseRelation.objects.filter(
        expense_id=expense_id
    ).values_list('product_id', flat=True)

    all_product_ids = set(product_ids_from_recipes) | set(product_ids_from_relations)

    if all_product_ids:
        ProductCostSnapshot.objects.filter(
            product_id__in=all_product_ids
        ).update(is_outdated=True)


# =============================================================================
# RECIPE SIGNALS
# =============================================================================

@receiver(post_save, sender=Recipe)
def on_recipe_saved(sender, instance: Recipe, created: bool, **kwargs):
    """
    При сохранении рецепта — помечаем снапшот товара как устаревший.
    """
    ProductCostSnapshot.objects.filter(
        product=instance.product
    ).update(is_outdated=True)

    logger.info(
        f"Снапшот товара {instance.product_id} помечен как устаревший "
        f"(рецепт {'создан' if created else 'обновлён'})"
    )


@receiver(post_delete, sender=Recipe)
def on_recipe_deleted(sender, instance: Recipe, **kwargs):
    """
    При удалении рецепта — помечаем снапшот товара как устаревший.
    """
    ProductCostSnapshot.objects.filter(
        product=instance.product
    ).update(is_outdated=True)

    logger.info(f"Снапшот товара {instance.product_id} помечен как устаревший (рецепт удалён)")


# =============================================================================
# PRODUCT EXPENSE RELATION SIGNALS (Legacy)
# =============================================================================

@receiver(post_save, sender=ProductExpenseRelation)
def on_relation_saved(sender, instance: ProductExpenseRelation, created: bool, **kwargs):
    """
    При сохранении связи товар-расход — помечаем снапшот как устаревший.
    """
    ProductCostSnapshot.objects.filter(
        product=instance.product
    ).update(is_outdated=True)


@receiver(post_delete, sender=ProductExpenseRelation)
def on_relation_deleted(sender, instance: ProductExpenseRelation, **kwargs):
    """
    При удалении связи товар-расход — помечаем снапшот как устаревший.
    """
    ProductCostSnapshot.objects.filter(
        product=instance.product
    ).update(is_outdated=True)
