# apps/orders/signals.py

from typing import Optional

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import (
    OrderHistory,
    OrderReturn,
    OrderReturnStatus,
    OrderType,
    PartnerOrder,
    StoreOrder,
)


def _get_old_status(instance) -> Optional[str]:
    if not instance.pk:
        return None
    model = type(instance)
    try:
        old = model.objects.get(pk=instance.pk)
    except model.DoesNotExist:
        return None
    return old.status


@receiver(pre_save, sender=PartnerOrder)
def partner_order_pre_save(sender, instance: PartnerOrder, **kwargs):
    instance._old_status = _get_old_status(instance)


@receiver(post_save, sender=PartnerOrder)
def partner_order_post_save(sender, instance: PartnerOrder, created, **kwargs):
    old_status = getattr(instance, "_old_status", None)
    if created:
        # историю создания создаём в сервисе
        return
    if old_status and old_status != instance.status:
        OrderHistory.objects.create(
            order_type=OrderType.PARTNER,
            order_id=instance.pk,
            old_status=old_status,
            new_status=instance.status,
            changed_by=None,
            comment="Смена статуса партнёрского заказа (через сохранение)",
        )


@receiver(pre_save, sender=StoreOrder)
def store_order_pre_save(sender, instance: StoreOrder, **kwargs):
    instance._old_status = _get_old_status(instance)


@receiver(post_save, sender=StoreOrder)
def store_order_post_save(sender, instance: StoreOrder, created, **kwargs):
    old_status = getattr(instance, "_old_status", None)
    if created:
        return
    if old_status and old_status != instance.status:
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=instance.pk,
            old_status=old_status,
            new_status=instance.status,
            changed_by=None,
            comment="Смена статуса заказа магазина (через сохранение)",
        )


@receiver(pre_save, sender=OrderReturn)
def order_return_pre_save(sender, instance: OrderReturn, **kwargs):
    instance._old_status = _get_old_status(instance)


@receiver(post_save, sender=OrderReturn)
def order_return_post_save(sender, instance: OrderReturn, created, **kwargs):
    old_status = getattr(instance, "_old_status", None)
    if created:
        return
    if old_status and old_status != instance.status:
        OrderHistory.objects.create(
            order_type=OrderType.RETURN,
            order_id=instance.pk,
            old_status=old_status,
            new_status=instance.status,
            changed_by=None,
            comment="Смена статуса возврата (через сохранение)",
        )
