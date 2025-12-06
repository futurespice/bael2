# apps/notifications/models.py
"""
Модели для уведомлений согласно ТЗ v2.0.

ТИПЫ УВЕДОМЛЕНИЙ:
- Новое сообщение из чатов
- Изменился статус заказа
- Сделан новый заказ
- Добавился новый магазин
- Сделан расход (для партнёров)
- Пришёл заказ (для партнёров)
"""

from django.conf import settings
from django.db import models


class NotificationType(models.TextChoices):
    """Типы уведомлений согласно ТЗ v2.0."""
    NEW_MESSAGE = 'new_message', 'Новое сообщение'
    ORDER_STATUS_CHANGED = 'order_status_changed', 'Изменился статус заказа'
    NEW_ORDER = 'new_order', 'Новый заказ'
    NEW_STORE = 'new_store', 'Новый магазин'
    EXPENSE_ADDED = 'expense_added', 'Добавлен расход'
    ORDER_ARRIVED = 'order_arrived', 'Пришёл заказ'


class Notification(models.Model):
    """
    Уведомление пользователя.
    
    ТЗ v2.0: Push-уведомления через FCM
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Получатель'
    )

    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        verbose_name='Тип уведомления'
    )

    title = models.CharField(
        max_length=200,
        verbose_name='Заголовок'
    )

    message = models.TextField(
        verbose_name='Сообщение'
    )

    # Связь с объектом (заказ, магазин и т.д.)
    related_object_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='Тип связанного объекта'
    )

    related_object_id = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name='ID связанного объекта'
    )

    is_read = models.BooleanField(
        default=False,
        verbose_name='Прочитано'
    )

    is_pushed = models.BooleanField(
        default=False,
        verbose_name='Push отправлен'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Создано'
    )

    read_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Прочитано в'
    )

    class Meta:
        db_table = 'notifications'
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['notification_type']),
        ]

    def __str__(self):
        return f"{self.user} - {self.title}"

    def mark_as_read(self):
        """Отметить как прочитанное."""
        from django.utils import timezone
        
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class FCMToken(models.Model):
    """
    FCM токен устройства для push-уведомлений.
    
    ТЗ v2.0: Firebase Cloud Messaging для push-уведомлений
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='fcm_tokens',
        verbose_name='Пользователь'
    )

    token = models.CharField(
        max_length=500,
        unique=True,
        verbose_name='FCM Token'
    )

    device_type = models.CharField(
        max_length=20,
        choices=[
            ('android', 'Android'),
            ('ios', 'iOS'),
            ('web', 'Web'),
        ],
        default='android',
        verbose_name='Тип устройства'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Создан'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Обновлён'
    )

    class Meta:
        db_table = 'fcm_tokens'
        verbose_name = 'FCM Token'
        verbose_name_plural = 'FCM Tokens'
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return f"{self.user} - {self.device_type}"
