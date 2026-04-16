"""
Одноразовый бэкфил: разложить существующие DebtPayment (в т.ч. с order=NULL)
по StoreOrder.paid_amount, чтобы order.outstanding_debt совпадал с фактом.

Идемпотентен: для каждого магазина сбрасывает paid_amount у ACCEPTED-заказов
и распределяет Sum(DebtPayment) FIFO по дате подтверждения.

Транзакция на магазин (не на весь прогон) — чтобы не держать длинную блокировку
и не мешать работающему API.

Запуск:
  docker compose exec -T web python manage.py shell < scripts/heal_paid_amounts.py
"""
import traceback
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

store_ids = list(Store.objects.filter(is_active=True).values_list('pk', flat=True))
print(f"Магазинов к обработке: {len(store_ids)}\n")

for store_id in store_ids:
    try:
        with transaction.atomic():
            store = Store.objects.select_for_update().get(pk=store_id)

            paid_total = DebtPayment.objects.filter(store=store).aggregate(
                s=Sum('amount')
            )['s'] or Decimal('0')

            if paid_total <= 0:
                continue

            StoreOrder.objects.select_for_update().filter(
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
                apply_amount = min(order.debt_amount, remaining)
                StoreOrder.objects.filter(pk=order.pk).update(paid_amount=apply_amount)
                remaining -= apply_amount

            distributed = paid_total - remaining
            total_stores += 1
            total_distributed += distributed
            total_unallocated += remaining

            tail = f"  (без заказа: {remaining})" if remaining > 0 else ""
            print(f"{store.name} (id={store.id}): оплат {paid_total}, разложено {distributed}{tail}")
    except Exception as e:
        print(f"[ERROR] store id={store_id}: {e}")
        traceback.print_exc()

print("=" * 70)
print(f"Обработано магазинов: {total_stores}")
print(f"Всего разложено: {total_distributed}")
print(f"Не привязано (оплат больше, чем долгов по заказам): {total_unallocated}")
print("=" * 70)
