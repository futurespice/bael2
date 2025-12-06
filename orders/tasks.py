# apps/orders/tasks.py
"""
Celery задачи для заказов (v2.0).

ИЗМЕНЕНИЯ v2.0:
- Удалён OrderReturn (не используется в новой архитектуре)
- Упрощены задачи под новый workflow
"""

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)


# =============================================================================
# EMAIL УВЕДОМЛЕНИЯ
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_order_status_email(self, order_id: int, status: str):
    """
    Отправить email уведомление о смене статуса заказа.
    
    Args:
        order_id: ID заказа
        status: Новый статус
    """
    try:
        from .models import StoreOrder
        
        order = StoreOrder.objects.select_related('store', 'partner').get(id=order_id)
        
        # Формируем сообщение
        status_messages = {
            'pending': 'создан и ожидает обработки',
            'in_transit': 'одобрен администратором и в пути',
            'accepted': 'подтверждён партнёром',
            'rejected': 'отклонён',
        }
        
        message = f"""
Заказ #{order_id} {status_messages.get(status, status)}

Магазин: {order.store.name}
Сумма: {order.total_amount} сом
Дата: {order.created_at.strftime('%d.%m.%Y %H:%M')}

---
БайЭл - B2B платформа
        """
        
        # Получатели
        recipients = []
        
        # Уведомляем магазин
        if order.store.created_by and order.store.created_by.email:
            recipients.append(order.store.created_by.email)
        
        # Уведомляем партнёра при определённых статусах
        if order.partner and order.partner.email and status in ['in_transit', 'accepted']:
            recipients.append(order.partner.email)
        
        for email in recipients:
            send_mail(
                subject=f'Заказ #{order_id} - {status_messages.get(status, status)}',
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=True,
            )
        
        logger.info(f"Email уведомления отправлены для заказа #{order_id}")
        
    except Exception as exc:
        logger.error(f"Ошибка отправки email для заказа #{order_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_new_order_notification(self, order_id: int):
    """
    Уведомить админов о новом заказе.
    
    Args:
        order_id: ID заказа
    """
    try:
        from .models import StoreOrder
        from users.models import User
        
        order = StoreOrder.objects.select_related('store').get(id=order_id)
        
        message = f"""
Новый заказ #{order_id}

Магазин: {order.store.name}
Адрес: {order.store.address}
Сумма: {order.total_amount} сом
Дата: {order.created_at.strftime('%d.%m.%Y %H:%M')}

---
БайЭл - B2B платформа
        """
        
        # Отправляем всем админам
        admin_emails = User.objects.filter(
            role='admin',
            is_active=True
        ).exclude(email='').values_list('email', flat=True)
        
        for email in admin_emails:
            send_mail(
                subject=f'Новый заказ #{order_id} от {order.store.name}',
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=True,
            )
        
        logger.info(f"Уведомления о новом заказе #{order_id} отправлены админам")
        
    except Exception as exc:
        logger.error(f"Ошибка уведомления о новом заказе #{order_id}: {exc}")
        raise self.retry(exc=exc)


# =============================================================================
# НАПОМИНАНИЯ
# =============================================================================

@shared_task
def send_pending_orders_reminder():
    """
    Напомнить о заказах в статусе 'pending' более 24 часов.
    
    Запускается периодически через Celery Beat.
    """
    from .models import StoreOrder, StoreOrderStatus
    from users.models import User
    from datetime import timedelta
    
    threshold = timezone.now() - timedelta(hours=24)
    
    pending_orders = StoreOrder.objects.filter(
        status=StoreOrderStatus.PENDING,
        created_at__lt=threshold
    ).select_related('store')
    
    if not pending_orders.exists():
        logger.info("Нет заказов, ожидающих более 24 часов")
        return
    
    # Формируем сводку
    order_list = "\n".join([
        f"- Заказ #{o.id} от {o.store.name} ({o.created_at.strftime('%d.%m.%Y')})"
        for o in pending_orders[:20]  # Максимум 20 в письме
    ])
    
    message = f"""
Внимание! Есть заказы, ожидающие обработки более 24 часов:

{order_list}

Всего: {pending_orders.count()} заказ(ов)

---
БайЭл - B2B платформа
    """
    
    # Отправляем админам
    admin_emails = User.objects.filter(
        role='admin',
        is_active=True
    ).exclude(email='').values_list('email', flat=True)
    
    for email in admin_emails:
        send_mail(
            subject=f'Напоминание: {pending_orders.count()} заказов ожидают обработки',
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=True,
        )
    
    logger.info(f"Напоминание отправлено: {pending_orders.count()} заказов")


# =============================================================================
# ОТЧЁТЫ
# =============================================================================

@shared_task
def generate_daily_stats_report():
    """
    Генерация ежедневного отчёта по заказам.
    
    Запускается в конце дня через Celery Beat.
    """
    from .models import StoreOrder, StoreOrderStatus
    from users.models import User
    from datetime import date
    
    today = date.today()
    
    # Собираем статистику за день
    orders_today = StoreOrder.objects.filter(created_at__date=today)
    
    stats = {
        'total_orders': orders_today.count(),
        'pending': orders_today.filter(status=StoreOrderStatus.PENDING).count(),
        'in_transit': orders_today.filter(status=StoreOrderStatus.IN_TRANSIT).count(),
        'accepted': orders_today.filter(status=StoreOrderStatus.ACCEPTED).count(),
        'rejected': orders_today.filter(status=StoreOrderStatus.REJECTED).count(),
        'total_amount': sum(o.total_amount for o in orders_today.filter(status=StoreOrderStatus.ACCEPTED)),
    }
    
    message = f"""
Ежедневный отчёт за {today.strftime('%d.%m.%Y')}

📊 Заказы:
- Всего создано: {stats['total_orders']}
- В ожидании: {stats['pending']}
- В пути: {stats['in_transit']}
- Принято: {stats['accepted']}
- Отклонено: {stats['rejected']}

💰 Сумма принятых заказов: {stats['total_amount']} сом

---
БайЭл - B2B платформа
    """
    
    # Отправляем админам
    admin_emails = User.objects.filter(
        role='admin',
        is_active=True
    ).exclude(email='').values_list('email', flat=True)
    
    for email in admin_emails:
        send_mail(
            subject=f'Ежедневный отчёт БайЭл за {today.strftime("%d.%m.%Y")}',
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=True,
        )
    
    logger.info(f"Ежедневный отчёт за {today} отправлен")
    return stats


# =============================================================================
# ОЧИСТКА
# =============================================================================

@shared_task
def cleanup_old_order_history():
    """
    Удалить старую историю заказов (старше 1 года).
    
    Запускается еженедельно через Celery Beat.
    """
    from .models import OrderHistory
    from datetime import timedelta
    
    threshold = timezone.now() - timedelta(days=365)
    
    deleted, _ = OrderHistory.objects.filter(
        created_at__lt=threshold
    ).delete()
    
    logger.info(f"Удалено {deleted} старых записей истории заказов")
    return deleted
