# apps/stores/tasks.py
"""
Celery задачи для магазинов (v2.0).
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def recalculate_store_debts():
    """
    Пересчитать долги всех магазинов.
    
    Синхронизация долгов из заказов.
    """
    from decimal import Decimal
    from django.db.models import Sum
    from .models import Store
    from orders.models import StoreOrder, StoreOrderStatus
    
    stores = Store.objects.filter(is_active=True)
    updated = 0
    
    for store in stores:
        # Сумма долгов из принятых заказов
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED
        )
        
        total_debt = orders.aggregate(
            debt=Sum('debt_amount')
        )['debt'] or Decimal('0')
        
        total_paid = orders.aggregate(
            paid=Sum('paid_amount')
        )['paid'] or Decimal('0')
        
        actual_debt = total_debt - total_paid
        
        if store.debt != actual_debt:
            store.debt = actual_debt
            store.total_paid = total_paid
            store.save(update_fields=['debt', 'total_paid'])
            updated += 1
    
    logger.info(f"Пересчитаны долги {updated} магазинов")
    return {'updated': updated}


@shared_task
def send_debt_reminders():
    """
    Отправить напоминания магазинам с долгом более 7 дней.
    """
    from datetime import timedelta
    from decimal import Decimal
    from django.utils import timezone
    from django.conf import settings
    from django.core.mail import send_mail
    from .models import Store
    
    threshold = timezone.now() - timedelta(days=7)
    
    # Магазины с долгом и без оплат более 7 дней
    stores_with_debt = Store.objects.filter(
        debt__gt=Decimal('0'),
        is_active=True
    )
    
    sent = 0
    for store in stores_with_debt:
        if store.created_by and store.created_by.email:
            message = f"""
Уважаемый {store.owner_name}!

Напоминаем, что за магазином "{store.name}" числится непогашенный долг в размере {store.debt} сом.

Просим погасить задолженность в ближайшее время.

---
БайЭл - B2B платформа
            """
            
            try:
                send_mail(
                    subject=f'Напоминание о задолженности - {store.name}',
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[store.created_by.email],
                    fail_silently=True,
                )
                sent += 1
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания {store.name}: {e}")
    
    logger.info(f"Отправлено {sent} напоминаний о долгах")
    return {'sent': sent}
