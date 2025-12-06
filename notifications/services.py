# apps/notifications/services.py
"""
Сервисы для работы с уведомлениями.

СРЕДНЯЯ проблема #27: Сигналы для уведомлений
"""

import logging
from typing import Optional, List

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from .models import Notification, FCMToken, NotificationType

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Сервис для создания и управления уведомлениями.
    """

    @classmethod
    @transaction.atomic
    def create_notification(
            cls,
            *,
            user,
            notification_type: str,
            title: str,
            message: str,
            related_object_type: Optional[str] = None,
            related_object_id: Optional[int] = None,
            send_push: bool = True
    ) -> Notification:
        """
        Создать уведомление.
        
        Args:
            user: Получатель
            notification_type: Тип уведомления
            title: Заголовок
            message: Сообщение
            related_object_type: Тип связанного объекта
            related_object_id: ID связанного объекта
            send_push: Отправить push-уведомление
            
        Returns:
            Notification
        """
        notification = Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            related_object_type=related_object_type,
            related_object_id=related_object_id
        )
        
        if send_push:
            cls._send_push_notification(notification)
        
        logger.info(f"Создано уведомление #{notification.id} для пользователя {user.id}")
        return notification

    @classmethod
    def _send_push_notification(cls, notification: Notification):
        """
        Отправить push-уведомление через FCM.
        
        TODO: Реализовать интеграцию с Firebase Cloud Messaging
        """
        try:
            # Получаем активные FCM токены пользователя
            tokens = FCMToken.objects.filter(
                user=notification.user,
                is_active=True
            ).values_list('token', flat=True)
            
            if not tokens:
                logger.info(f"Нет активных FCM токенов для пользователя {notification.user.id}")
                return
            
            # TODO: Отправка через firebase-admin
            # from firebase_admin import messaging
            # 
            # message = messaging.MulticastMessage(
            #     notification=messaging.Notification(
            #         title=notification.title,
            #         body=notification.message
            #     ),
            #     tokens=list(tokens)
            # )
            # 
            # response = messaging.send_multicast(message)
            # 
            # notification.is_pushed = True
            # notification.save(update_fields=['is_pushed'])
            
            logger.info(f"Push-уведомление для #{notification.id} будет отправлено на {len(tokens)} устройств")
            
        except Exception as e:
            logger.error(f"Ошибка отправки push-уведомления: {e}")

    @classmethod
    def get_user_notifications(
            cls,
            user,
            unread_only: bool = False,
            notification_type: Optional[str] = None
    ) -> QuerySet[Notification]:
        """
        Получить уведомления пользователя.
        
        Args:
            user: Пользователь
            unread_only: Только непрочитанные
            notification_type: Фильтр по типу
            
        Returns:
            QuerySet уведомлений
        """
        queryset = Notification.objects.filter(user=user)
        
        if unread_only:
            queryset = queryset.filter(is_read=False)
            
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
            
        return queryset.order_by('-created_at')

    @classmethod
    def get_unread_count(cls, user) -> int:
        """Количество непрочитанных уведомлений."""
        return Notification.objects.filter(user=user, is_read=False).count()

    @classmethod
    @transaction.atomic
    def mark_as_read(cls, notification_id: int, user) -> Optional[Notification]:
        """Отметить уведомление как прочитанное."""
        try:
            notification = Notification.objects.get(id=notification_id, user=user)
            notification.mark_as_read()
            return notification
        except Notification.DoesNotExist:
            return None

    @classmethod
    @transaction.atomic
    def mark_all_as_read(cls, user) -> int:
        """Отметить все уведомления как прочитанные."""
        count = Notification.objects.filter(
            user=user,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
        
        logger.info(f"Отмечено как прочитанные {count} уведомлений для пользователя {user.id}")
        return count

    @classmethod
    @transaction.atomic
    def delete_all(cls, user) -> int:
        """Удалить все уведомления пользователя."""
        count, _ = Notification.objects.filter(user=user).delete()
        logger.info(f"Удалено {count} уведомлений для пользователя {user.id}")
        return count


class FCMTokenService:
    """
    Сервис для управления FCM токенами.
    """

    @classmethod
    @transaction.atomic
    def register_token(
            cls,
            *,
            user,
            token: str,
            device_type: str = 'android'
    ) -> FCMToken:
        """
        Зарегистрировать FCM токен устройства.
        
        Args:
            user: Пользователь
            token: FCM токен
            device_type: Тип устройства
            
        Returns:
            FCMToken
        """
        # Деактивируем старый токен если он уже существует
        FCMToken.objects.filter(token=token).update(is_active=False)
        
        # Создаём или обновляем токен
        fcm_token, created = FCMToken.objects.update_or_create(
            user=user,
            token=token,
            defaults={
                'device_type': device_type,
                'is_active': True
            }
        )
        
        action = "зарегистрирован" if created else "обновлён"
        logger.info(f"FCM токен {action} для пользователя {user.id}")
        
        return fcm_token

    @classmethod
    @transaction.atomic
    def deactivate_token(cls, token: str) -> bool:
        """Деактивировать FCM токен."""
        count = FCMToken.objects.filter(token=token).update(is_active=False)
        return count > 0

    @classmethod
    def get_user_tokens(cls, user) -> QuerySet[FCMToken]:
        """Получить активные токены пользователя."""
        return FCMToken.objects.filter(user=user, is_active=True)
