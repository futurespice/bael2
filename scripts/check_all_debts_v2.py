"""
Показать ВСЕ магазины с долгом > 0, с разбивкой до/после 3 апреля 2026.

Запуск:
  docker compose exec -T web python manage.py shell < scripts/check_all_debts_v2.py
"""
from decimal import Decimal
from datetime import datetime
from django.utils import timezone
from django.db.models import Sum
from stores.models import Store
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct

CUTOFF = timezone.make_aware(datetime(2026, 4, 3, 0, 0, 0))

print("=" * 90)
print(f"ВСЕ МАГАЗИНЫ С ДОЛГОМ (граница: {CUTOFF.date()})")
print("=" * 90)

stores = Store.objects.filter(is_active=True, debt__gt=0).order_by('-debt')
total_current = Decimal('0')
total_old_debt = Decimal('0')
total_new_debt = Decimal('0')

for store in stores:
    total_current += store.debt

    # --- Старые заказы (до 3 апреля 2026) ---
    old_orders = StoreOrder.objects.filter(
        store=store, status=StoreOrderStatus.ACCEPTED, created_at__lt=CUTOFF
    )
    old_agg = old_orders.aggregate(total=Sum('total_amount'), prepaid=Sum('prepayment_amount'))
    old_total = old_agg['total'] or Decimal('0')
    old_prepaid = old_agg['prepaid'] or Decimal('0')
    old_count = old_orders.count()

    old_payments = DebtPayment.objects.filter(
        store=store, created_at__lt=CUTOFF
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    old_defects = DefectiveProduct.objects.filter(
        order__store=store, order__status=StoreOrderStatus.ACCEPTED,
        order__created_at__lt=CUTOFF,
        status=DefectiveProduct.DefectStatus.APPROVED
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    old_debt = max(old_total - old_prepaid - old_payments - old_defects, Decimal('0'))
    total_old_debt += old_debt

    # --- Новые заказы (с 3 апреля 2026) ---
    new_orders = StoreOrder.objects.filter(
        store=store, status=StoreOrderStatus.ACCEPTED, created_at__gte=CUTOFF
    )
    new_agg = new_orders.aggregate(total=Sum('total_amount'), prepaid=Sum('prepayment_amount'))
    new_total = new_agg['total'] or Decimal('0')
    new_prepaid = new_agg['prepaid'] or Decimal('0')
    new_count = new_orders.count()

    new_payments = DebtPayment.objects.filter(
        store=store, created_at__gte=CUTOFF
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    new_defects = DefectiveProduct.objects.filter(
        order__store=store, order__status=StoreOrderStatus.ACCEPTED,
        order__created_at__gte=CUTOFF,
        status=DefectiveProduct.DefectStatus.APPROVED
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    new_debt = max(new_total - new_prepaid - new_payments - new_defects, Decimal('0'))
    total_new_debt += new_debt

    print(f"\n{'─' * 70}")
    print(f"  {store.name} (ID={store.id})")
    print(f"  Текущий store.debt: {store.debt}")
    if old_count > 0:
        print(f"  ДО 3 апр: {old_count} заказов, долг={old_debt} (заказы={old_total} преопл={old_prepaid} оплаты={old_payments} дефекты={old_defects})")
    else:
        print(f"  ДО 3 апр: нет заказов")
    if new_count > 0:
        print(f"  С 3 апр:  {new_count} заказов, долг={new_debt} (заказы={new_total} преопл={new_prepaid} оплаты={new_payments} дефекты={new_defects})")
    else:
        print(f"  С 3 апр:  нет заказов")

print(f"\n{'=' * 90}")
print(f"Всего магазинов с долгом: {stores.count()}")
print(f"Общая сумма текущих долгов: {total_current} сом")
print(f"Из них СТАРЫЙ долг (до 3 апр, должен быть 0): {total_old_debt} сом")
print(f"Из них НОВЫЙ долг (с 3 апр, правильный):      {total_new_debt} сом")
print(f"{'=' * 90}")
