# apps/products/signals.py
"""Сигналы для products (БЕЗ ИЗМЕНЕНИЙ)."""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ProductExpenseRelation


@receiver(post_save, sender=ProductExpenseRelation)
def recalculate_product_price_on_expense_change(sender, instance, **kwargs):
    """Пересчёт цены при изменении расходов (опционально)."""
    # Отключено для производительности
    # instance.product.save()
    pass