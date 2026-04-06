"""
Исправление долгов: обнулить старые (до 3 апреля 2026), оставить только новые.

Для старых заказов — обнуляем debt_amount (чтобы статистика тоже была чистой).
Для store.debt — пересчитываем только из новых заказов.

Запуск:
  docker compose exec -T web python manage.py shell < scripts/fix_debts_v2.py
"""
from decimal import Decimal
from datetime import datetime
from django.utils import timezone
from django.db.models import Sum
from stores.models import Store
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct

CUTOFF = timezone.make_aware(datetime(2026, 4, 3, 0, 0, 0))

print("=" * 70)
print("ИСПРАВЛЕНИЕ ДОЛГОВ")
print("=" * 70)

# 1. Обнуляем debt_amount у старых ACCEPTED заказов
old_orders = StoreOrder.objects.filter(
    status=StoreOrderStatus.ACCEPTED,
    created_at__lt=CUTOFF,
    debt_amount__gt=0
)
old_count = old_orders.count()
old_orders.update(debt_amount=Decimal('0'))
print(f"\n1) Обнулено debt_amount у {old_count} старых заказов (до 3 апр)")

# 2. Пересчитываем store.debt только из новых заказов
stores = Store.objects.filter(is_active=True, debt__gt=0)
fixed = 0

print(f"\n2) Пересчёт store.debt:")

for store in stores:
    # Только новые заказы
    new_orders = StoreOrder.objects.filter(
        store=store, status=StoreOrderStatus.ACCEPTED, created_at__gte=CUTOFF
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

    correct_debt = max(new_total - new_prepaid - new_payments - new_defects, Decimal('0'))
    correct_total_paid = new_prepaid + new_payments

    old_debt = store.debt
    if old_debt != correct_debt:
        store.debt = correct_debt
        store.total_paid = correct_total_paid
        store.save(update_fields=['debt', 'total_paid'])
        fixed += 1
        print(f"  {store.name}: {old_debt} -> {correct_debt}")

print(f"\nИсправлено магазинов: {fixed}")
print(f"{'=' * 70}")
