"""
ВОССТАНОВЛЕНИЕ ДОЛГОВ после зачистки 18.04.2026 (Option C).

ПРОБЛЕМА:
  scripts/wipe_all_debts.py обнулил у всех ACCEPTED заказов поля
  debt_amount и paid_amount, удалил все DebtPayment и обнулил
  Store.debt/total_paid. Затем админ выставил Store.debt вручную
  для 10 магазинов; остальные накопили долг от новых заказов.

  В результате эндпоинты статистики (get_store_history,
  PartnerStatistics, PartnerDebtViewSet, админка магазина и т.д.)
  показывают неверные суммы, потому что order.debt_amount = 0
  и DebtPayment-ов нет.

РЕШЕНИЕ (Option C):
  1. Идентифицируем "зачисточные" заказы:
     - status = ACCEPTED
     - debt_amount = 0
     - paid_amount = 0
     - total_amount > prepayment_amount
     - нет DebtPayment, привязанных к этому заказу

  2. Восстанавливаем debt_amount = total_amount − prepayment_amount.

  3. Для каждого магазина считаем сумму к погашению:
        needed = Σ(restored_debt_amount) − Store.debt
     (Store.debt — источник правды: выставлен админом или растёт от
      новых заказов после зачистки)

  4. FIFO (от старых заказов к новым) гасим через Order.pay_debt:
        amount = min(order.outstanding_debt, remaining)
        received_by = order.partner
     Это создаёт DebtPayment с правильной привязкой к заказу
     и обновляет paid_amount.

  ИНВАРИАНТ ПОСЛЕ ПРОГОНА:
    Store.debt == Σ(order.outstanding_debt) для ACCEPTED заказов

  Все эндпоинты статистики начнут отображать правильные данные:
    - Formula A (Σorder.debt_amount): debt_amount восстановлен ✓
    - Formula B (Σtotal − Σprepayment − Σpayments): payments созданы ✓
    - Formula C (Store.debt): не трогаем, остаётся правдой ✓
    - Formula D (outstanding_debt = debt_amount − paid_amount): ✓

ИДЕМПОТЕНТНОСТЬ:
  Если для магазина уже есть DebtPayment с пометкой "Бэкфил..." —
  пропускаем (повторный прогон ничего не сломает).

ЗАПУСК:
  # 1. Сначала dry-run (ничего не меняет, только печатает план):
  docker compose exec -T web python manage.py shell < scripts/backfill_phantom_debt.py

  # 2. Боевой запуск (только после ручной проверки dry-run):
  docker compose exec -T web env APPLY=1 python manage.py shell < scripts/backfill_phantom_debt.py
"""
import os
from datetime import datetime, timezone
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Q, Sum

from orders.models import (
    DebtPayment,
    OrderHistory,
    OrderType,
    StoreOrder,
    StoreOrderStatus,
    StoreOrderType,
)
from stores.models import Store

APPLY = os.environ.get('APPLY') == '1'
COMMENT = 'Бэкфил после зачистки долгов 18.04.2026'
PHANTOM_NOTES = 'Корректирующий заказ: долг подтверждён заказчиком 18.04.2026'
WIPE_DATE = datetime(2026, 4, 18, 0, 0, 0, tzinfo=timezone.utc)

# Фаза 2: ручное переопределение партнёра для phantom-магазинов.
# Если store_id здесь нет — берётся партнёр с большинством ACCEPTED заказов
# у этого магазина. Если у магазина нет вообще заказов — нужно явно указать.
# Формат: {store_id: partner_user_id}
PHANTOM_PARTNER_OVERRIDE: dict[int, int] = {
    # 135: 8,   # пример: Халмион Гайрат ака → Эрзатбек (id=8)
}

print('=' * 78)
print(f"ВОССТАНОВЛЕНИЕ ДОЛГОВ (Option C)   режим: "
      f"{'APPLY (боевой)' if APPLY else 'DRY-RUN'}")
print('=' * 78)

stats = {
    'stores_processed': 0,
    'orders_restored': 0,
    'payments_created': 0,
    'amount_absorbed': Decimal('0'),
    'skipped_already_done': 0,
    'phantom_orders_created': 0,
    'phantom_amount': Decimal('0'),
}
problems: list[str] = []
# Фаза 2: магазины где formula < Store.debt — нужен корректирующий заказ.
# Список (store, gap) копится в фазе 1, обрабатывается после неё.
phantom_cases: list[tuple[Store, Decimal]] = []

for store in Store.objects.filter(is_active=True).order_by('name'):
    # ─── Идемпотентность ───────────────────────────────────────
    if DebtPayment.objects.filter(store=store, comment=COMMENT).exists():
        stats['skipped_already_done'] += 1
        continue

    # ─── Шаг 1: считаем formula_now (как PartnerDebtViewSet) ───
    # Это «то, что показывают эндпоинты» прямо сейчас.
    # Учитываем ВСЕ ACCEPTED заказы (пред+пост-зачистка)
    # и ВСЕ DebtPayment (order-привязанные + прямые order=None).
    accepted = StoreOrder.objects.filter(
        store=store,
        status=StoreOrderStatus.ACCEPTED,
    )
    agg = accepted.aggregate(t=Sum('total_amount'), p=Sum('prepayment_amount'))
    total = agg['t'] or Decimal('0')
    prepay = agg['p'] or Decimal('0')

    paid = DebtPayment.objects.filter(
        Q(order__store=store, order__status=StoreOrderStatus.ACCEPTED)
        | Q(order__isnull=True, store=store)
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    formula_now = (total - prepay - paid).quantize(Decimal('0.01'))
    target = store.debt
    needed = (formula_now - target).quantize(Decimal('0.01'))

    # ─── Если формула уже совпадает — ничего не делаем ──────────
    if needed == Decimal('0'):
        continue

    # ─── Если формула < Store.debt — фантомный долг.
    # Откладываем в фазу 2 (создание корректирующего заказа). ──
    if needed < Decimal('0'):
        gap = (target - formula_now).quantize(Decimal('0.01'))
        phantom_cases.append((store, gap))
        continue

    # ─── Шаг 2: находим "зачисточные" заказы ───────────────────
    # Признаки: ACCEPTED, debt_amount=0, paid_amount=0,
    # total > prepayment, нет привязанных DebtPayment.
    wiped_orders_qs = (
        StoreOrder.objects
        .filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED,
            debt_amount=Decimal('0'),
            paid_amount=Decimal('0'),
            total_amount__gt=F('prepayment_amount'),
        )
        .annotate(linked_payments=Sum('debt_payments__amount'))
        .filter(linked_payments__isnull=True)
        .order_by('confirmed_at', 'id')
    )
    wiped_orders = list(wiped_orders_qs)

    if not wiped_orders:
        problems.append(
            f"  ! {store.name}: needed={needed}, но нет зачисточных заказов "
            f"для гашения (странно — formula > Store.debt без причины)"
        )
        continue

    # ─── Восстанавливаем debt_amount у зачисточных заказов ──────
    sum_restored = Decimal('0')
    for o in wiped_orders:
        restored = (o.total_amount - o.prepayment_amount).quantize(Decimal('0.01'))
        o._restored_debt = restored
        sum_restored += restored

    if sum_restored < needed:
        problems.append(
            f"  ! {store.name}: needed={needed}, "
            f"но Σrestored_debt={sum_restored} меньше — не хватит ёмкости"
        )
        continue

    print(f"\n  {store.name}:")
    print(f"      formula_now={formula_now}, Store.debt={target}, "
          f"к погашению: {needed}")
    print(f"      зачисточных заказов: {len(wiped_orders)}, "
          f"Σrestored_debt: {sum_restored}")

    # ─── Шаг 3+4: восстановление + FIFO-гашение в одной транзакции ──
    if APPLY:
        with transaction.atomic():
            # Восстанавливаем debt_amount
            for o in wiped_orders:
                StoreOrder.objects.filter(pk=o.pk).update(debt_amount=o._restored_debt)
            # FIFO гасим через Order.pay_debt
            remaining = needed
            for o in wiped_orders:
                if remaining <= Decimal('0'):
                    break
                fresh = StoreOrder.objects.select_for_update().get(pk=o.pk)
                outstanding = fresh.outstanding_debt
                amount = min(outstanding, remaining).quantize(Decimal('0.01'))
                if amount <= Decimal('0'):
                    continue
                fresh.pay_debt(
                    amount=amount,
                    paid_by=None,
                    received_by=fresh.partner,
                    comment=COMMENT,
                )
                remaining -= amount
                stats['payments_created'] += 1
            stats['orders_restored'] += len(wiped_orders)
            stats['amount_absorbed'] += (needed - remaining)
            if remaining > Decimal('0'):
                problems.append(
                    f"  ! {store.name}: не хватило заказов чтобы погасить "
                    f"остаток {remaining}"
                )
    else:
        # Dry-run: просто печатаем план
        remaining = needed
        for o in wiped_orders:
            if remaining <= Decimal('0'):
                break
            outstanding = o._restored_debt  # paid_amount=0 у зачисточных
            amount = min(outstanding, remaining).quantize(Decimal('0.01'))
            if amount <= Decimal('0'):
                continue
            partner_name = (
                o.partner.get_full_name() or o.partner.username
                if o.partner else '<нет партнёра>'
            )
            print(f"        → заказ #{o.id} ({o.confirmed_at.date()}): "
                  f"pay_debt({amount}) → {partner_name}")
            remaining -= amount
            stats['payments_created'] += 1
        stats['orders_restored'] += len(wiped_orders)
        stats['amount_absorbed'] += (needed - remaining)
        if remaining > Decimal('0'):
            problems.append(
                f"  ! {store.name}: не хватит заказов чтобы погасить "
                f"остаток {remaining}"
            )

    stats['stores_processed'] += 1


# ════════════════════════════════════════════════════════════════
# ФАЗА 2: Phantom-долги (formula < Store.debt без подкрепления заказами)
# ════════════════════════════════════════════════════════════════
# Создаём по одному корректирующему ACCEPTED заказу без позиций
# на gap-сумму. Партнёр: PHANTOM_PARTNER_OVERRIDE[store_id] или
# auto-detect (партнёр с большинством ACCEPTED заказов магазина).

if phantom_cases:
    print('\n' + '─' * 78)
    print('ФАЗА 2: корректирующие заказы для phantom-долгов')
    print('─' * 78)

for store, gap in phantom_cases:
    # ─── Идемпотентность: по idempotency_key ────────────────────
    idem_key = f'phantom_correction_store_{store.id}'
    if StoreOrder.objects.filter(idempotency_key=idem_key).exists():
        stats['skipped_already_done'] += 1
        continue

    # ─── Определяем партнёра ────────────────────────────────────
    partner = None
    if store.id in PHANTOM_PARTNER_OVERRIDE:
        from users.models import User
        try:
            partner = User.objects.get(
                pk=PHANTOM_PARTNER_OVERRIDE[store.id], role='partner'
            )
        except User.DoesNotExist:
            problems.append(
                f"  ! {store.name}: PHANTOM_PARTNER_OVERRIDE указывает на "
                f"несуществующего партнёра id={PHANTOM_PARTNER_OVERRIDE[store.id]}"
            )
            continue
    else:
        # Auto-detect: партнёр с большинством ACCEPTED заказов
        top = (
            StoreOrder.objects
            .filter(store=store, status=StoreOrderStatus.ACCEPTED, partner__isnull=False)
            .values('partner')
            .annotate(c=Count('id'))
            .order_by('-c', 'partner')
            .first()
        )
        if not top:
            problems.append(
                f"  ! {store.name}: gap={gap}, нет партнёра в истории заказов. "
                f"Добавь в PHANTOM_PARTNER_OVERRIDE[{store.id}] = <partner_id>"
            )
            continue
        from users.models import User
        partner = User.objects.get(pk=top['partner'])

    partner_name = f"{partner.name} {partner.second_name}".strip() or partner.username

    print(f"\n  {store.name} (id={store.id}):")
    print(f"      gap={gap}, корректирующий заказ → {partner_name}")

    if APPLY:
        with transaction.atomic():
            # 1. Создаём заказ
            order = StoreOrder.objects.create(
                store=store,
                partner=partner,
                status=StoreOrderStatus.ACCEPTED,
                order_type=StoreOrderType.MANUAL,
                total_amount=gap,
                prepayment_amount=Decimal('0'),
                debt_amount=gap,
                paid_amount=Decimal('0'),
                confirmed_by=partner,
                confirmed_at=WIPE_DATE,
                notes=PHANTOM_NOTES,
                idempotency_key=idem_key,
            )
            # 2. Подменяем created_at на дату зачистки (auto_now_add не даёт
            #    указать в create — обновляем отдельно через update())
            StoreOrder.objects.filter(pk=order.pk).update(created_at=WIPE_DATE)
            # 3. История
            OrderHistory.objects.create(
                order_type=OrderType.STORE,
                order_id=order.id,
                old_status='created',
                new_status=StoreOrderStatus.ACCEPTED,
                changed_by=partner,
                comment=(
                    f'{PHANTOM_NOTES}. Сумма: {gap} сом. Долг: {gap} сом. '
                    f'Создан скриптом backfill_phantom_debt.py.'
                ),
            )
            stats['phantom_orders_created'] += 1
            stats['phantom_amount'] += gap
    else:
        stats['phantom_orders_created'] += 1
        stats['phantom_amount'] += gap


# ─── Итоги ──────────────────────────────────────────────────────
print('\n' + '=' * 78)
print('ИТОГО:')
verb = 'создано' if APPLY else 'будет создано'
print(f"  Обработано магазинов:              {stats['stores_processed']}")
print(f"  Заказов с восст. debt_amount:      {stats['orders_restored']}")
print(f"  DebtPayment {verb}:    {stats['payments_created']}")
print(f"  Сумма погашения:                   {stats['amount_absorbed']}")
print(f"  Phantom-заказов {verb}:        {stats['phantom_orders_created']}")
print(f"  Сумма phantom-долгов:              {stats['phantom_amount']}")
print(f"  Пропущено (уже бэкфилены):         {stats['skipped_already_done']}")
if problems:
    print(f"\n  ПРОБЛЕМЫ ({len(problems)}):")
    for p in problems:
        print(p)
print('=' * 78)
if not APPLY:
    print('DRY-RUN завершён. Запусти с APPLY=1 для применения.')
print('=' * 78)
