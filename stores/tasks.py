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

    Синхронизация долгов из заказов, платежей (DebtPayment) и дефектов.

    ВАЖНО:
    - pay_store_debt НЕ обновляет StoreOrder.paid_amount, поэтому
      используем DebtPayment.amount (как в ReportService).
    - Одобренные дефекты уменьшают Store.debt, но не StoreOrder.debt_amount,
      поэтому вычитаем их вручную.
    """
    from decimal import Decimal
    from django.db.models import Sum
    from .models import Store
    from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct

    stores = Store.objects.filter(is_active=True)
    updated = 0

    for store in stores:
        # Принятые заказы магазина
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED
        )

        # Исходный долг из заказов
        total_debt = orders.aggregate(
            debt=Sum('debt_amount')
        )['debt'] or Decimal('0')

        # Предоплата из заказов
        total_prepayment = orders.aggregate(
            prepaid=Sum('prepayment_amount')
        )['prepaid'] or Decimal('0')

        # Погашения через DebtPayment (pay_store_debt создаёт записи здесь,
        # а НЕ обновляет StoreOrder.paid_amount)
        debt_payments = DebtPayment.objects.filter(
            order__store=store,
            order__status=StoreOrderStatus.ACCEPTED
        ).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        # Одобренные дефекты уменьшают долг
        defect_amount = DefectiveProduct.objects.filter(
            order__store=store,
            order__status=StoreOrderStatus.ACCEPTED,
            status=DefectiveProduct.DefectStatus.APPROVED
        ).aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0')

        total_paid = total_prepayment + debt_payments
        actual_debt = total_debt - debt_payments - defect_amount
        if actual_debt < Decimal('0'):
            actual_debt = Decimal('0')

        if store.debt != actual_debt or store.total_paid != total_paid:
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
