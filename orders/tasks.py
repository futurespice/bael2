# apps/orders/tasks.py
"""
Асинхронные задачи приложения orders.
Поддержка: django-q, Celery
Уведомления: Email, Telegram, Firebase Push
Используется в signals.py
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.db import transaction

# django-q или celery
try:
    from django_q.tasks import async_task
    DJANGO_Q = True
except ImportError:
    from celery import shared_task
    async_task = shared_task
    DJANGO_Q = False

# Telegram
try:
    import requests
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

# Firebase Push (FCM)
try:
    from firebase_admin.messaging import Message, Notification, send
    import firebase_admin
    FCM_AVAILABLE = True
except ImportError:
    FCM_AVAILABLE = False

from .models import PartnerOrder, StoreOrder, OrderReturn, OrderHistory
from users.models import User
from stores.models import Store

logger = logging.getLogger('orders.tasks')


# =============================================================================
#  УТИЛИТЫ
# =============================================================================

def safe_str(value: Any) -> str:
    return str(value) if value is not None else ""


def get_order_url(order_type: str, order_id: int) -> str:
    """Генерация URL для фронтенда"""
    base = settings.FRONTEND_URL.rstrip("/")
    mapping = {
        'partner': f"{base}/partner/orders/{order_id}",
        'store': f"{base}/store/orders/{order_id}",
        'return': f"{base}/partner/returns/{order_id}",
    }
    return mapping.get(order_type, base)


# =============================================================================
#  EMAIL УВЕДОМЛЕНИЯ
# =============================================================================

def send_email_notification(
    to_email: str,
    subject: str,
    template_name: str,
    context: Dict[str, Any]
) -> None:
    """Отправка HTML + текст email"""
    try:
        html_content = render_to_string(template_name, context)
        text_content = strip_tags(html_content)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email]
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()

        logger.info(f"Email отправлен: {to_email} | {subject}")
    except Exception as e:
        logger.error(f"Ошибка отправки email {to_email}: {e}", exc_info=True)
        raise


# =============================================================================
#  TELEGRAM УВЕДОМЛЕНИЯ
# =============================================================================

def send_telegram_notification(chat_id: str, text: str) -> None:
    """Отправка в Telegram"""
    if not TELEGRAM_AVAILABLE or not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram не настроен")
        return

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Telegram error: {response.text}")
        else:
            logger.info(f"Telegram отправлено: @{chat_id}")
    except Exception as e:
        logger.error(f"Telegram отправка не удалась: {e}", exc_info=True)


# =============================================================================
#  PUSH УВЕДОМЛЕНИЯ (FCM)
# =============================================================================

def send_push_notification(token: str, title: str, body: str, data: Dict[str, str]) -> None:
    """Отправка push через Firebase"""
    if not FCM_AVAILABLE:
        logger.warning("FCM не инициализирован")
        return

    message = Message(
        notification=Notification(title=title, body=body),
        token=token,
        data=data
    )

    try:
        response = send(message)
        logger.info(f"Push отправлен: {token} | {response}")
    except Exception as e:
        logger.error(f"Push ошибка: {e}", exc_info=True)


# =============================================================================
#  ОСНОВНЫЕ ЗАДАЧИ
# =============================================================================

@async_task
def send_status_notification_task(
    order_type: str,
    order_id: int,
    status: str,
    retry: int = 3
) -> None:
    """
    Универсальная задача: уведомление о смене статуса
    Поддерживает: PartnerOrder, StoreOrder, OrderReturn
    """
    logger.info(f"Запуск уведомления: {order_type} #{order_id} → {status}")

    order = None
    user = None
    store = None

    try:
        if order_type == 'partner':
            order = PartnerOrder.objects.select_related('partner').get(id=order_id)
            user = order.partner
        elif order_type == 'store':
            order = StoreOrder.objects.select_related('store', 'partner').get(id=order_id)
            user = order.partner
            store = order.store
        elif order_type == 'return':
            order_return = OrderReturn.objects.select_related('order__store', 'order__partner').get(id=order_id)
            user = order_return.order.partner
            store = order_return.order.store
            order = order_return
        else:
            logger.error(f"Неизвестный тип заказа: {order_type}")
            return

    except Exception as e:
        logger.error(f"Заказ не найден: {order_type} #{order_id} | {e}")
        return

    # Контекст
    context = {
        'order_id': order_id,
        'order_type': order_type,
        'status': status,
        'status_display': order.get_status_display() if hasattr(order, 'get_status_display') else status,
        'total': getattr(order, 'total_amount', Decimal('0')),
        'url': get_order_url(order_type, order_id),
        'user': user,
        'store': store,
        'timestamp': timezone.localtime()
    }

    # Email
    if user.email and getattr(user, 'email_notifications', True):
        template = f"emails/order_{order_type}_{status}.html"
        subject = f"Заказ #{order_id} — {context['status_display']}"
        try:
            send_email_notification(user.email, subject, template, context)
        except Exception as e:
            logger.warning(f"Email не отправлен: {e}")

    # Telegram
    if getattr(user, 'telegram_chat_id', None):
        text = render_to_string(f"telegram/order_{order_type}_{status}.txt", context)
        send_telegram_notification(user.telegram_chat_id, text)

    # Push
    if getattr(user, 'fcm_token', None):
        send_push_notification(
            token=user.fcm_token,
            title=f"Заказ #{order_id}",
            body=context['status_display'],
            data={
                'type': 'order_status',
                'order_id': str(order_id),
                'status': status,
                'url': context['url']
            }
        )

    # История (дубль на случай, если сигнал не сработал)
    with transaction.atomic():
        OrderHistory.objects.get_or_create(
            order_type=order_type,
            order_id=order_id,
            type='notification',
            defaults={
                'amount': getattr(order, 'total_amount', Decimal('0')),
                'note': f'Уведомление: {status}'
            }
        )

    logger.info(f"Уведомление завершено: {order_type} #{order_id}")


# =============================================================================
#  ДОПОЛНИТЕЛЬНЫЕ ЗАДАЧИ
# =============================================================================

@async_task
def send_order_reminder(partner_id: int, days: int = 3) -> None:
    """Напоминание о невыполненных заказах"""
    try:
        partner = User.objects.get(id=partner_id, role='partner')
    except User.DoesNotExist:
        return

    pending_orders = PartnerOrder.objects.filter(
        partner=partner,
        status='pending',
        created_at__lte=timezone.now() - timezone.timedelta(days=days)
    ).count()

    if pending_orders == 0:
        return

    context = {
        'user': partner,
        'count': pending_orders,
        'days': days,
        'url': f"{settings.FRONTEND_URL}/partner/orders"
    }

    # Email
    send_email_notification(
        to_email=partner.email,
        subject=f"У вас {pending_orders} необработанных заказов",
        template_name="emails/order_reminder.html",
        context=context
    )

    logger.info(f"Напоминание отправлено: {partner.email} ({pending_orders} заказов)")


@async_task
def generate_daily_report(date: Optional[str] = None) -> None:
    """Ежедневный отчёт по заказам"""
    from datetime import date as dt_date
    target_date = dt_date.fromisoformat(date) if date else timezone.localdate()

    # Статистика
    stats = {
        'partner_orders': PartnerOrder.objects.filter(created_at__date=target_date).count(),
        'store_orders': StoreOrder.objects.filter(created_at__date=target_date).count(),
        'returns': OrderReturn.objects.filter(created_at__date=target_date).count(),
        'total_amount': Decimal('0'),
    }

    for order in PartnerOrder.objects.filter(created_at__date=target_date):
        stats['total_amount'] += order.total_amount
    for order in StoreOrder.objects.filter(created_at__date=target_date):
        stats['total_amount'] += order.total_amount

    context = {
        'date': target_date,
        'stats': stats,
        'url': f"{settings.FRONTEND_URL}/admin/reports"
    }

    # Отправка админу
    admin_emails = User.objects.filter(role='admin', is_active=True).values_list('email', flat=True)
    for email in admin_emails:
        if email:
            send_email_notification(
                to_email=email,
                subject=f"Отчёт за {target_date}",
                template_name="emails/daily_report.html",
                context=context
            )

    logger.info(f"Ежедневный отчёт отправлен за {target_date}")


# =============================================================================
#  ПРИМЕР ШАБЛОНОВ (создать в templates/)
# =============================================================================

"""
templates/emails/order_partner_confirmed.html
templates/emails/order_store_fulfilled.html
templates/emails/order_return_approved.html
templates/emails/order_reminder.html
templates/emails/daily_report.html

templates/telegram/order_partner_confirmed.txt
...
"""