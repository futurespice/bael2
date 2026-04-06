"""
Скрипт диагностики долгов магазинов.

Запуск:
  python manage.py shell < scripts/check_debts.py

Показывает расхождения между текущим store.debt и правильным расчётом.
НЕ меняет данные — только выводит.
"""
from decimal import Decimal
from django.db.models import Sum
from stores.models import Store
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct

print("=" * 80)
print("ДИАГНОСТИКА ДОЛГОВ МАГАЗИНОВ")
print("=" * 80)

stores = Store.objects.filter(is_active=True)
total_diff = Decimal('0')
problems = []

for store in stores:
    # Суммы из принятых заказов
    orders = StoreOrder.objects.filter(store=store, status=StoreOrderStatus.ACCEPTED)
    agg = orders.aggregate(
        total=Sum('total_amount'),
        prepaid=Sum('prepayment_amount'),
    )
    total_orders = agg['total'] or Decimal('0')
    total_prepaid = agg['prepaid'] or Decimal('0')

    # ВСЕ оплаты через DebtPayment — и с order, и без (order=null)
    all_payments = DebtPayment.objects.filter(store=store).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')

    # Одобренные дефекты
    defects = DefectiveProduct.objects.filter(
        order__store=store,
        order__status=StoreOrderStatus.ACCEPTED,
        status=DefectiveProduct.DefectStatus.APPROVED
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    correct_debt = max(total_orders - total_prepaid - all_payments - defects, Decimal('0'))
    diff = store.debt - correct_debt

    if diff != Decimal('0'):
        total_diff += diff
        problems.append({
            'store': store,
            'current_debt': store.debt,
            'correct_debt': correct_debt,
            'diff': diff,
            'total_orders': total_orders,
            'total_prepaid': total_prepaid,
            'all_payments': all_payments,
            'defects': defects,
        })
        print(f"\n❌ {store.name} (ID={store.id})")
        print(f"   Текущий долг:    {store.debt}")
        print(f"   Правильный долг: {correct_debt}")
        print(f"   Разница:         {diff:+}")
        print(f"   ---")
        print(f"   Сумма заказов:   {total_orders}")
        print(f"   Предоплата:      {total_prepaid}")
        print(f"   Оплаты (DebtPayment): {all_payments}")
        print(f"   Дефекты:         {defects}")

if problems:
    print(f"\n{'=' * 80}")
    print(f"ИТОГО: {len(problems)} магазинов с расхождениями")
    print(f"Общая разница: {total_diff:+} сом")
    print(f"\nДля исправления запустите: python manage.py shell < scripts/fix_debts.py")
else:
    print("\n✅ Все долги корректны, расхождений нет.")
