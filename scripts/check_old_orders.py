"""
Проверка старых ACCEPTED заказов с непогашенным debt_amount.

Запуск:
  docker compose exec -T web python manage.py shell < scripts/check_old_orders.py
"""
from decimal import Decimal
from datetime import datetime
from django.utils import timezone
from django.db.models import Sum, F, Q
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment

CUTOFF = timezone.make_aware(datetime(2025, 4, 3, 0, 0, 0))

print("=" * 90)
print("СТАРЫЕ ACCEPTED ЗАКАЗЫ (до 3 апреля) с debt_amount > 0")
print("=" * 90)

old_orders = StoreOrder.objects.filter(
    status=StoreOrderStatus.ACCEPTED,
    created_at__lt=CUTOFF,
    debt_amount__gt=0
).select_related('store').order_by('store__name', 'created_at')

total_old_debt = Decimal('0')
store_totals = {}

for order in old_orders:
    # Оплаты по этому заказу
    paid = DebtPayment.objects.filter(order=order).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')

    remaining = max(order.debt_amount - paid, Decimal('0'))
    total_old_debt += remaining

    sname = order.store.name
    if sname not in store_totals:
        store_totals[sname] = {'store_id': order.store_id, 'debt': Decimal('0'), 'orders': 0}
    store_totals[sname]['debt'] += remaining
    store_totals[sname]['orders'] += 1

    print(f"  Заказ #{order.id} | {order.store.name} (ID={order.store_id}) | "
          f"создан {order.created_at.strftime('%Y-%m-%d %H:%M')} | "
          f"total={order.total_amount} prepaid={order.prepayment_amount} "
          f"debt_amount={order.debt_amount} paid={paid} остаток={remaining}")

print(f"\n{'=' * 90}")
print(f"ИТОГО по магазинам:")
for name, data in sorted(store_totals.items(), key=lambda x: -x[1]['debt']):
    if data['debt'] > 0:
        print(f"  {name} (ID={data['store_id']}): {data['orders']} заказов, долг={data['debt']}")

print(f"\nВсего старых заказов с долгом: {old_orders.count()}")
print(f"Общая сумма старого долга: {total_old_debt} сом")

# Также проверим ВСЕ заказы до 3 апреля (любой статус)
print(f"\n{'=' * 90}")
print("Все заказы до 3 апреля по статусам:")
for status_choice in StoreOrderStatus.choices:
    count = StoreOrder.objects.filter(
        created_at__lt=CUTOFF, status=status_choice[0]
    ).count()
    if count > 0:
        total = StoreOrder.objects.filter(
            created_at__lt=CUTOFF, status=status_choice[0]
        ).aggregate(s=Sum('debt_amount'))['s'] or 0
        print(f"  {status_choice[1]}: {count} заказов, debt_amount sum={total}")
