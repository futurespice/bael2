"""
ОДНОРАЗОВАЯ ЗАЧИСТКА ВСЕХ ДОЛГОВ.

Что делает:
1. Удаляет ВСЕ DebtPayment.
2. Обнуляет Store.debt и Store.total_paid у всех магазинов.
3. Обнуляет StoreOrder.debt_amount и StoreOrder.paid_amount у всех ACCEPTED заказов.

После запуска долги выставляются вручную через админку магазина (поле "Текущий долг").

ВАЖНО: бэкап БД сделан заранее. Операция необратимая.

Запуск:
  docker compose exec -T web python manage.py shell < scripts/wipe_all_debts.py
"""
from decimal import Decimal
from django.db import transaction
from stores.models import Store
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment

print("=" * 70)
print("WIPE: полная зачистка долгов")
print("=" * 70)

with transaction.atomic():
    payments_count = DebtPayment.objects.count()
    DebtPayment.objects.all().delete()
    print(f"Удалено DebtPayment: {payments_count}")

    stores_updated = Store.objects.exclude(
        debt=Decimal('0'), total_paid=Decimal('0')
    ).update(debt=Decimal('0'), total_paid=Decimal('0'))
    print(f"Обнулено Store.debt/total_paid: {stores_updated}")

    orders_updated = StoreOrder.objects.filter(
        status=StoreOrderStatus.ACCEPTED
    ).exclude(
        debt_amount=Decimal('0'), paid_amount=Decimal('0')
    ).update(debt_amount=Decimal('0'), paid_amount=Decimal('0'))
    print(f"Обнулено StoreOrder (ACCEPTED): {orders_updated}")

print("=" * 70)
print("ГОТОВО. Теперь выставь долги 12 магазинам через админку магазина.")
print("=" * 70)
