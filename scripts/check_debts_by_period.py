"""
Диагностика долгов с разбивкой по периодам.

Показывает для каждого магазина с долгом:
- Долг из заказов ДО 3 апреля (должен быть 0, т.к. был обнулён вручную)
- Долг из заказов С 3 апреля (новые заказы, правильный долг)

Запуск:
  docker compose exec -T web python manage.py shell < scripts/check_debts_by_period.py
"""
from decimal import Decimal
from datetime import datetime
from django.utils import timezone
from django.db.models import Sum
from stores.models import Store
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct

# Граница: заказы до этой даты были обнулены вручную
CUTOFF = timezone.make_aware(datetime(2025, 4, 3, 0, 0, 0))

print("=" * 90)
print(f"РАЗБИВКА ДОЛГОВ ПО ПЕРИОДАМ (граница: {CUTOFF.date()})")
print("=" * 90)

stores = Store.objects.filter(is_active=True, debt__gt=0)
total_old_debt = Decimal('0')

for store in stores:
    # --- Старые заказы (до 3 апреля) ---
    old_orders = StoreOrder.objects.filter(
        store=store, status=StoreOrderStatus.ACCEPTED,
        created_at__lt=CUTOFF
    )
    old_agg = old_orders.aggregate(
        total=Sum('total_amount'), prepaid=Sum('prepayment_amount')
    )
    old_total = old_agg['total'] or Decimal('0')
    old_prepaid = old_agg['prepaid'] or Decimal('0')

    old_payments = DebtPayment.objects.filter(
        store=store, created_at__lt=CUTOFF
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    old_defects = DefectiveProduct.objects.filter(
        order__store=store, order__status=StoreOrderStatus.ACCEPTED,
        order__created_at__lt=CUTOFF,
        status=DefectiveProduct.DefectStatus.APPROVED
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    old_debt = max(old_total - old_prepaid - old_payments - old_defects, Decimal('0'))

    # --- Новые заказы (с 3 апреля) ---
    new_orders = StoreOrder.objects.filter(
        store=store, status=StoreOrderStatus.ACCEPTED,
        created_at__gte=CUTOFF
    )
    new_agg = new_orders.aggregate(
        total=Sum('total_amount'), prepaid=Sum('prepayment_amount')
    )
    new_total = new_agg['total'] or Decimal('0')
    new_prepaid = new_agg['prepaid'] or Decimal('0')

    new_payments = DebtPayment.objects.filter(
        store=store, created_at__gte=CUTOFF
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    new_defects = DefectiveProduct.objects.filter(
        order__store=store, order__status=StoreOrderStatus.ACCEPTED,
        order__created_at__gte=CUTOFF,
        status=DefectiveProduct.DefectStatus.APPROVED
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    new_debt = max(new_total - new_prepaid - new_payments - new_defects, Decimal('0'))

    if old_debt > 0:
        total_old_debt += old_debt
        print(f"\n{'❌' if old_debt > 0 else '✅'} {store.name} (ID={store.id})")
        print(f"   Текущий store.debt:  {store.debt}")
        print(f"   Долг до 3 апр:      {old_debt}  ← должен быть 0 (был обнулён)")
        print(f"   Долг с 3 апр:       {new_debt}  ← правильный новый долг")
        print(f"   Правильный долг:    {new_debt}")
        print(f"   Разница (лишнее):   +{old_debt}")
        print(f"   --- до 3 апр: заказы={old_total} преопл={old_prepaid} оплаты={old_payments} дефекты={old_defects}")
        print(f"   --- с 3 апр:  заказы={new_total} преопл={new_prepaid} оплаты={new_payments} дефекты={new_defects}")
    elif store.debt != new_debt:
        print(f"\n⚠️  {store.name} (ID={store.id})")
        print(f"   Текущий store.debt:  {store.debt}")
        print(f"   Долг до 3 апр:      {old_debt}")
        print(f"   Долг с 3 апр:       {new_debt}")
        print(f"   Разница:            {store.debt - new_debt:+}")

print(f"\n{'=' * 90}")
print(f"Итого лишний долг из старых заказов (до 3 апр): {total_old_debt} сом")
print(f"{'=' * 90}")
