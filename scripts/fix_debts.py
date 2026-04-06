"""
Скрипт исправления долгов магазинов.

Запуск:
  python manage.py shell < scripts/fix_debts.py

СНАЧАЛА запустите check_debts.py чтобы увидеть расхождения!
"""
from decimal import Decimal
from django.db.models import Sum
from stores.models import Store
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct

print("=" * 80)
print("ИСПРАВЛЕНИЕ ДОЛГОВ МАГАЗИНОВ")
print("=" * 80)

stores = Store.objects.filter(is_active=True)
fixed = 0

for store in stores:
    orders = StoreOrder.objects.filter(store=store, status=StoreOrderStatus.ACCEPTED)
    agg = orders.aggregate(
        total=Sum('total_amount'),
        prepaid=Sum('prepayment_amount'),
    )
    total_orders = agg['total'] or Decimal('0')
    total_prepaid = agg['prepaid'] or Decimal('0')

    # ВСЕ оплаты — ключевое отличие от старой задачи
    all_payments = DebtPayment.objects.filter(store=store).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')

    defects = DefectiveProduct.objects.filter(
        order__store=store,
        order__status=StoreOrderStatus.ACCEPTED,
        status=DefectiveProduct.DefectStatus.APPROVED
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    correct_debt = max(total_orders - total_prepaid - all_payments - defects, Decimal('0'))
    correct_total_paid = total_prepaid + all_payments

    if store.debt != correct_debt or store.total_paid != correct_total_paid:
        old_debt = store.debt
        old_paid = store.total_paid
        store.debt = correct_debt
        store.total_paid = correct_total_paid
        store.save(update_fields=['debt', 'total_paid'])
        fixed += 1
        print(f"✅ {store.name}: долг {old_debt} → {correct_debt}, оплачено {old_paid} → {correct_total_paid}")

print(f"\nИсправлено: {fixed} магазинов")
