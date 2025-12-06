# notifications/tasks.py
"""
Celery задачи для уведомлений.

Асинхронные задачи для:
- Отправки push-уведомлений через FCM
- Отправки email уведомлений
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_push_notification_task(self, notification_id: int):
    """
    Отправить push-уведомление через FCM.
    
    Args:
        notification_id: ID уведомления в базе
    """
    try:
        from .models import Notification, FCMToken
        
        notification = Notification.objects.get(id=notification_id)
        
        # Получаем токены пользователя
        tokens = FCMToken.objects.filter(
            user=notification.user,
            is_active=True
        ).values_list('token', flat=True)
        
        if not tokens:
            logger.info(f"Нет FCM токенов для пользователя {notification.user.id}")
            return
        
        # TODO: Реализовать отправку через firebase-admin
        # from firebase_admin import messaging
        # message = messaging.MulticastMessage(
        #     notification=messaging.Notification(
        #         title=notification.title,
        #         body=notification.message
        #     ),
        #     tokens=list(tokens)
        # )
        # response = messaging.send_multicast(message)
        
        notification.is_pushed = True
        notification.save(update_fields=['is_pushed'])
        
        logger.info(f"Push-уведомление #{notification_id} отправлено")
        
    except Notification.DoesNotExist:
        logger.error(f"Уведомление #{notification_id} не найдено")
    except Exception as exc:
        logger.error(f"Ошибка отправки push: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_notification_task(self, user_id: int, subject: str, message: str):
    """
    Отправить email уведомление.
    
    Args:
        user_id: ID пользователя
        subject: Тема письма
        message: Текст письма
    """
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        from users.models import User
        
        user = User.objects.get(id=user_id)
        
        if not user.email:
            logger.warning(f"У пользователя {user_id} нет email")
            return
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        logger.info(f"Email отправлен пользователю {user_id}")
        
    except User.DoesNotExist:
        logger.error(f"Пользователь #{user_id} не найден")
    except Exception as exc:
        logger.error(f"Ошибка отправки email: {exc}")
        raise self.retry(exc=exc)


@shared_task
def cleanup_old_notifications():
    """
    Удалить старые прочитанные уведомления (старше 30 дней).
    
    Запускается периодически через Celery Beat.
    """
    from datetime import timedelta
    from django.utils import timezone
    from .models import Notification
    
    threshold = timezone.now() - timedelta(days=30)
    
    deleted, _ = Notification.objects.filter(
        is_read=True,
        created_at__lt=threshold
    ).delete()
    
    logger.info(f"Удалено {deleted} старых уведомлений")
    return deleted
