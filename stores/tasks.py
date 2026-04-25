# apps/stores/tasks.py
"""
Celery задачи для магазинов (v2.0).
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


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
