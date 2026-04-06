"""
Исправление 5 магазинов, у которых задача recalculate_store_debts
не учитывала DebtPayment без привязки к заказу (order=null).

Запуск:
  docker compose exec -T web python manage.py shell < scripts/fix_debts.py
"""
from decimal import Decimal
from django.db.models import Sum
from stores.models import Store
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct

# Магазины с подтверждённым расхождением
STORE_IDS = [318, 322, 328, 298, 102]

print("=" * 70)
print("ИСПРАВЛЕНИЕ ДОЛГОВ")
print("=" * 70)

for store_id in STORE_IDS:
    store = Store.objects.get(pk=store_id)
    old_debt = store.debt

    orders = StoreOrder.objects.filter(store=store, status=StoreOrderStatus.ACCEPTED)
    agg = orders.aggregate(total=Sum('total_amount'), prepaid=Sum('prepayment_amount'))
    total_orders = agg['total'] or Decimal('0')
    total_prepaid = agg['prepaid'] or Decimal('0')

    # ВСЕ оплаты — включая order=null
    all_payments = DebtPayment.objects.filter(store=store).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')

    defects = DefectiveProduct.objects.filter(
        order__store=store, order__status=StoreOrderStatus.ACCEPTED,
        status=DefectiveProduct.DefectStatus.APPROVED
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    correct_debt = max(total_orders - total_prepaid - all_payments - defects, Decimal('0'))
    correct_total_paid = total_prepaid + all_payments

    store.debt = correct_debt
    store.total_paid = correct_total_paid
    store.save(update_fields=['debt', 'total_paid'])

    print(f"  {store.name} (ID={store.id}): долг {old_debt} -> {correct_debt}")

print(f"\nГотово. Исправлено {len(STORE_IDS)} магазинов.")
