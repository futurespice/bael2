# apps/users/tasks.py
"""
Celery задачи для пользователей (v2.0).

Задачи для отправки email и очистки.
"""

import logging
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_welcome_email(self, user_id: int):
    """
    Отправить приветственное письмо новому пользователю.
    
    Args:
        user_id: ID пользователя
    """
    try:
        from .models import User
        
        user = User.objects.get(id=user_id)
        
        message = f"""
Здравствуйте, {user.name}!

Добро пожаловать в систему БайЭл!

Ваша роль: {user.get_role_display()}

Теперь вы можете начать работу в системе.

---
БайЭл - B2B платформа
        """
        
        send_mail(
            subject='Добро пожаловать в БайЭл!',
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        logger.info(f"Приветственное письмо отправлено: {user.email}")
        
    except Exception as exc:
        logger.error(f"Ошибка отправки письма пользователю {user_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, user_id: int, code: str):
    """
    Отправить код сброса пароля.
    
    Args:
        user_id: ID пользователя
        code: 5-значный код
    """
    try:
        from .models import User
        
        user = User.objects.get(id=user_id)
        
        message = f"""
Здравствуйте, {user.name}!

Вы запросили сброс пароля.

Ваш код для сброса пароля: {code}

Код действителен 15 минут.

Если вы не запрашивали сброс пароля, проигнорируйте это письмо.

---
БайЭл - B2B платформа
        """
        
        send_mail(
            subject='Код сброса пароля - БайЭл',
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        logger.info(f"Код сброса пароля отправлен: {user.email}")
        
    except Exception as exc:
        logger.error(f"Ошибка отправки кода пользователю {user_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task
def cleanup_expired_password_reset_requests():
    """
    Удалить просроченные запросы сброса пароля.
    """
    from django.utils import timezone
    from .models import PasswordResetRequest
    
    deleted, _ = PasswordResetRequest.objects.filter(
        expires_at__lt=timezone.now()
    ).delete()
    
    logger.info(f"Удалено {deleted} просроченных запросов сброса пароля")
    return {'deleted': deleted}


@shared_task
def cleanup_inactive_users():
    """
    Деактивировать пользователей без входа более 180 дней.
    """
    from datetime import timedelta
    from django.utils import timezone
    from .models import User
    
    threshold = timezone.now() - timedelta(days=180)
    
    # Только store пользователей, не админов и партнёров
    inactive = User.objects.filter(
        role='store',
        last_login__lt=threshold,
        is_active=True
    ).exclude(role__in=['admin', 'partner'])
    
    count = inactive.update(is_active=False)
    
    logger.info(f"Деактивировано {count} неактивных пользователей")
    return {'deactivated': count}
