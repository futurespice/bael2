"""
Одноразовый бэкфил: разложить существующие DebtPayment (в т.ч. с order=NULL)
по StoreOrder.paid_amount, чтобы order.outstanding_debt совпадал с фактом.

Идемпотентен: для каждого магазина сбрасывает paid_amount у ACCEPTED-заказов
и распределяет Sum(DebtPayment) FIFO по дате подтверждения.

Запуск:
  docker compose exec -T web python manage.py shell < scripts/heal_paid_amounts.py
"""
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from stores.models import Store
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment

print("=" * 70)
print("HEAL: распределение DebtPayment по StoreOrder.paid_amount")
print("=" * 70)

total_stores = 0
total_distributed = Decimal('0')
total_unallocated = Decimal('0')

with transaction.atomic():
    for store in Store.objects.filter(is_active=True):
        paid_total = DebtPayment.objects.filter(store=store).aggregate(
            s=Sum('amount')
        )['s'] or Decimal('0')

        if paid_total <= 0:
            continue

        StoreOrder.objects.filter(
            store=store, status=StoreOrderStatus.ACCEPTED
        ).update(paid_amount=Decimal('0'))

        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED,
            debt_amount__gt=0,
        ).order_by('confirmed_at', 'id')

        remaining = paid_total
        for order in orders:
            if remaining <= Decimal('0'):
                break
            apply = min(order.debt_amount, remaining)
            StoreOrder.objects.filter(pk=order.pk).update(paid_amount=apply)
            remaining -= apply

        distributed = paid_total - remaining
        total_stores += 1
        total_distributed += distributed
        total_unallocated += remaining

        tail = f"  (остаток без заказа: {remaining})" if remaining > 0 else ""
        print(f"{store.name} (id={store.id}): оплат {paid_total}, разложено {distributed}{tail}")

print("=" * 70)
print(f"Обработано магазинов: {total_stores}")
print(f"Всего разложено: {total_distributed}")
print(f"Всего не привязано (оплат больше, чем долгов по заказам): {total_unallocated}")
print("=" * 70)
