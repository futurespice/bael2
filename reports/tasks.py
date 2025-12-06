# apps/reports/tasks.py
"""
Celery задачи для отчётов (v2.0).

Задачи для генерации ежедневной статистики.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def generate_daily_report(report_date: str = None):
    """
    Генерация ежедневного отчёта.
    
    Собирает статистику за день и сохраняет в DailyReport.
    
    Args:
        report_date: Дата в формате 'YYYY-MM-DD', по умолчанию вчера
    """
    from .models import DailyReport
    from orders.models import StoreOrder, StoreOrderStatus, DefectiveProduct
    from products.models import PartnerExpense
    from stores.models import Store
    
    if report_date:
        target_date = date.fromisoformat(report_date)
    else:
        target_date = timezone.now().date() - timedelta(days=1)
    
    logger.info(f"Генерация отчёта за {target_date}")
    
    # Собираем данные по всем магазинам
    stores = Store.objects.filter(is_active=True)
    
    for store in stores:
        # Заказы магазина за день
        orders = StoreOrder.objects.filter(
            store=store,
            created_at__date=target_date,
            status=StoreOrderStatus.ACCEPTED
        )
        
        # Расчёт показателей
        income = sum(o.total_amount for o in orders)
        debt = sum(o.outstanding_debt for o in orders)
        paid_debt = sum(o.paid_amount for o in orders)
        orders_count = orders.count()
        
        # Бонусы (количество бонусных позиций)
        bonus_count = sum(
            item.quantity for o in orders 
            for item in o.items.filter(is_bonus=True)
        )
        
        # Брак
        defects = DefectiveProduct.objects.filter(
            order__store=store,
            created_at__date=target_date,
            status=DefectiveProduct.DefectStatus.APPROVED
        )
        defect_amount = sum(d.total_amount for d in defects)
        
        # Создаём или обновляем отчёт
        DailyReport.objects.update_or_create(
            date=target_date,
            store=store,
            partner=None,
            region=store.region,
            city=store.city,
            defaults={
                'income': income,
                'debt': debt,
                'paid_debt': paid_debt,
                'bonus_count': int(bonus_count),
                'defect_amount': defect_amount,
                'orders_count': orders_count,
            }
        )
    
    # Общий отчёт по расходам партнёров
    expenses = PartnerExpense.objects.filter(date=target_date)
    total_expenses = sum(e.amount for e in expenses)
    
    # Общий отчёт (без привязки к магазину)
    all_orders = StoreOrder.objects.filter(
        created_at__date=target_date,
        status=StoreOrderStatus.ACCEPTED
    )
    
    DailyReport.objects.update_or_create(
        date=target_date,
        store=None,
        partner=None,
        region=None,
        city=None,
        defaults={
            'income': sum(o.total_amount for o in all_orders),
            'debt': sum(o.outstanding_debt for o in all_orders),
            'paid_debt': sum(o.paid_amount for o in all_orders),
            'expenses': total_expenses,
            'orders_count': all_orders.count(),
        }
    )
    
    logger.info(f"Отчёт за {target_date} сгенерирован")
    return {'date': str(target_date), 'stores_processed': stores.count()}


@shared_task
def cleanup_old_reports(days: int = 365):
    """
    Удаление старых отчётов (старше года).
    
    Args:
        days: Сколько дней хранить отчёты
    """
    from .models import DailyReport
    
    threshold = timezone.now().date() - timedelta(days=days)
    
    deleted, _ = DailyReport.objects.filter(date__lt=threshold).delete()
    
    logger.info(f"Удалено {deleted} старых отчётов")
    return {'deleted': deleted}
