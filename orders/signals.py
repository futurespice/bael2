# apps/orders/signals.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Django сигналы для заказов.

СРЕДНЯЯ проблема #27: Добавлены сигналы для уведомлений

СИГНАЛЫ:
- store_order_pre_save / post_save: Отслеживание смены статуса
- Отправка уведомлений при смене статуса
"""

from typing import Optional
import logging

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import (
    OrderHistory,
    OrderType,
    PartnerOrder,
    StoreOrder,
    StoreOrderStatus,
)

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def _get_old_status(instance) -> Optional[str]:
    """Получить старый статус объекта."""
    if not instance.pk:
        return None
    model = type(instance)
    try:
        old = model.objects.get(pk=instance.pk)
    except model.DoesNotExist:
        return None
    return old.status


def _send_order_status_notification(order: StoreOrder, old_status: str, new_status: str):
    """
    Отправить уведомление о смене статуса заказа.
    
    ТЗ v2.0: Типы уведомлений включают "Изменился статус заказа"
    """
    try:
        # Импортируем здесь чтобы избежать circular import
        from notifications.services import NotificationService
        
        # Определяем получателей
        recipients = []
        
        # Магазин всегда получает уведомления
        if order.store and order.store.created_by:
            recipients.append(order.store.created_by)
        
        # Партнёр получает уведомления о заказах IN_TRANSIT
        if order.partner and new_status in [StoreOrderStatus.IN_TRANSIT, StoreOrderStatus.ACCEPTED]:
            recipients.append(order.partner)
        
        # Формируем сообщение
        status_messages = {
            StoreOrderStatus.IN_TRANSIT: 'одобрен администратором и находится в пути',
            StoreOrderStatus.ACCEPTED: 'подтверждён партнёром',
            StoreOrderStatus.REJECTED: 'отклонён',
        }
        
        message = status_messages.get(new_status, f'изменил статус на {new_status}')
        
        for recipient in recipients:
            NotificationService.create_notification(
                user=recipient,
                notification_type='order_status_changed',
                title='Изменение статуса заказа',
                message=f'Заказ #{order.id} {message}',
                related_object_type='store_order',
                related_object_id=order.id
            )
            
        logger.info(f"Уведомления о смене статуса заказа #{order.id} отправлены")
        
    except ImportError:
        logger.warning("Модуль notifications не установлен")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")


def _send_new_order_notification(order: StoreOrder):
    """
    Отправить уведомление о новом заказе.
    
    ТЗ v2.0: Типы уведомлений включают "Сделан новый заказ"
    """
    try:
        from notifications.services import NotificationService
        from users.models import User
        
        # Уведомляем всех админов о новом заказе
        admins = User.objects.filter(role='admin', is_active=True)
        
        for admin in admins:
            NotificationService.create_notification(
                user=admin,
                notification_type='new_order',
                title='Новый заказ',
                message=f'Магазин "{order.store.name}" создал новый заказ #{order.id}',
                related_object_type='store_order',
                related_object_id=order.id
            )
            
        logger.info(f"Уведомления о новом заказе #{order.id} отправлены админам")
        
    except ImportError:
        logger.warning("Модуль notifications не установлен")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")


# =============================================================================
# PARTNER ORDER SIGNALS
# =============================================================================

@receiver(pre_save, sender=PartnerOrder)
def partner_order_pre_save(sender, instance: PartnerOrder, **kwargs):
    """Сохраняем старый статус перед изменением."""
    instance._old_status = _get_old_status(instance)


@receiver(post_save, sender=PartnerOrder)
def partner_order_post_save(sender, instance: PartnerOrder, created, **kwargs):
    """Логируем изменение статуса партнёрского заказа."""
    old_status = getattr(instance, "_old_status", None)
    
    if created:
        # История создания формируется в сервисе
        return
        
    if old_status and old_status != instance.status:
        OrderHistory.objects.create(
            order_type=OrderType.PARTNER,
            order_id=instance.pk,
            old_status=old_status,
            new_status=instance.status,
            changed_by=None,
            comment="Смена статуса партнёрского заказа",
        )


# =============================================================================
# STORE ORDER SIGNALS
# =============================================================================

@receiver(pre_save, sender=StoreOrder)
def store_order_pre_save(sender, instance: StoreOrder, **kwargs):
    """Сохраняем старый статус перед изменением."""
    instance._old_status = _get_old_status(instance)


@receiver(post_save, sender=StoreOrder)
def store_order_post_save(sender, instance: StoreOrder, created, **kwargs):
    """
    Обработка после сохранения заказа магазина.
    
    Действия:
    1. Логирование изменения статуса в OrderHistory
    2. Отправка уведомлений при создании или смене статуса
    """
    old_status = getattr(instance, "_old_status", None)
    
    if created:
        # Уведомление о новом заказе
        _send_new_order_notification(instance)
        return
        
    if old_status and old_status != instance.status:
        # Логируем в историю
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=instance.pk,
            old_status=old_status,
            new_status=instance.status,
            changed_by=None,
            comment="Смена статуса заказа магазина",
        )
        
        # Отправляем уведомление
        _send_order_status_notification(instance, old_status, instance.status)


@receiver(post_save, sender=StoreOrder)
def handle_order_update(sender, instance, created, **kwargs):
    # ✅ ИСПРАВЛЕНИЕ ERROR-10: OrderHistory создаётся только в сервисах
    # Здесь только отправка уведомлений

    if not created and hasattr(instance, 'tracker'):
        if instance.tracker.has_changed('status'):
            from notifications.services import NotificationService

            # Уведомление магазину
            NotificationService.notify_order_status_changed(
                order=instance,
                old_status=instance.tracker.previous('status'),
                new_status=instance.status
            )

            # Уведомление партнёру
            if instance.partner:
                NotificationService.notify_partner_order_update(
                    partner=instance.partner,
                    order=instance
                )
