# apps/products/tasks.py
"""
Celery задачи для товаров (v2.0).

Задачи для пересчёта себестоимости и очистки.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def recalculate_product_costs():
    """
    Пересчитать себестоимость всех товаров.
    
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
