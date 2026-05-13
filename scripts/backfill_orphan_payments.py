"""
БЭКФИЛ ORPHAN-DEBTPAYMENT (FIFO) после фикса pay_store_debt.

ПРОБЛЕМА:
  До FIFO-фикса pay_store_debt создавал DebtPayment с order=NULL и обновлял
  только Store.debt — без синхронизации Order.paid_amount. Из-за этого
  отчёты /reports/statistics/, /reports/partners/statistics/,
  /reports/admin/partner-statistics/{id}/ показывали неверный debt:
  формула считала debt = Σorder.debt_amount − Σorder.paid_amount − defect,
  а orphan-платежи не попадали в Σpaid_amount → расхождение со Store.debt.

РЕШЕНИЕ:
  Раздать каждый orphan-DebtPayment по ACCEPTED заказам того же магазина
  (FIFO по confirmed_at):
    - если orphan.received_by задан → только по заказам этого партнёра;
    - если orphan.received_by=NULL → по всем заказам магазина;
  Создаём новые DebtPayment с order=..., копируем paid_by, received_by
  (или order.partner если в orphan было NULL), created_at оригинала.
  Обновляем order.paid_amount через F('paid_amount') + chunk.

  Оригинальный orphan сохраняется для аудита: amount уменьшается до
  непогашенного остатка (либо 0), в comment добавляется пометка
  '[FIFO-бэкфил orphan #...]'.

ИДЕМПОТЕНТНОСТЬ:
  Маркер '[FIFO-бэкфил orphan #<id>]' в comment. Повторный прогон
  пропускает orphan, у которого этот маркер уже есть.

ИНВАРИАНТ ПОСЛЕ ПРОГОНА:
  Для каждого магазина и каждого партнёра, у которого были orphan-платежи
  с подкреплением заказами:
    Σorder.paid_amount по заказам этого партнёра в этом магазине
      возросло ровно на сумму разнесённых orphan-платежей.
  Store.debt НЕ изменяется (мы не двигаем источник правды).

ЗАПУСК:
  # 1. Сначала dry-run (печатает план, ничего не меняет):
  docker compose exec -T web python manage.py shell < scripts/backfill_orphan_payments.py

  # 2. Боевой запуск:
  docker compose exec -T web env APPLY=1 python manage.py shell < scripts/backfill_orphan_payments.py
"""
import os
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from orders.models import DebtPayment, StoreOrder, StoreOrderStatus

APPLY = os.environ.get('APPLY') == '1'
MARKER_PREFIX = '[FIFO-бэкфил orphan'

print('=' * 78)
print(f"БЭКФИЛ ORPHAN-DEBTPAYMENT (FIFO)   режим: "
      f"{'APPLY (боевой)' if APPLY else 'DRY-RUN'}")
print('=' * 78)

stats = {
    'orphans_seen': 0,
    'orphans_skipped_idempotent': 0,
    'orphans_distributed_fully': 0,
    'orphans_distributed_partially': 0,
    'orphans_not_distributable': 0,
    'payments_created': 0,
    'amount_distributed': Decimal('0'),
    'amount_remaining_in_orphans': Decimal('0'),
}
problems: list[str] = []

# Берём только orphan с amount > 0 (нулевые — уже обработанные следы).
orphans_qs = DebtPayment.objects.filter(
    order__isnull=True,
    amount__gt=Decimal('0'),
).select_related('store', 'paid_by', 'received_by').order_by('created_at', 'id')

print(f'\nНайдено orphan-DebtPayment с amount > 0: {orphans_qs.count()}\n')

for orphan in orphans_qs:
    stats['orphans_seen'] += 1
    orphan_comment = orphan.comment or ''

    # Идемпотентность
    if MARKER_PREFIX in orphan_comment:
        stats['orphans_skipped_idempotent'] += 1
        continue

    store = orphan.store
    if store is None:
        problems.append(
            f'  ! orphan #{orphan.id}: store=NULL — нельзя разнести, пропуск'
        )
        stats['orphans_not_distributable'] += 1
        continue

    partner_filter_id = orphan.received_by_id  # None → все партнёры

    # ACCEPTED-заказы с непогашенным остатком, FIFO по дате подтверждения
    orders_qs = StoreOrder.objects.filter(
        store=store,
        status=StoreOrderStatus.ACCEPTED,
        debt_amount__gt=F('paid_amount'),
    )
    if partner_filter_id is not None:
        orders_qs = orders_qs.filter(partner_id=partner_filter_id)
    orders_list = list(orders_qs.order_by('confirmed_at', 'id'))

    remaining = orphan.amount
    distributed_chunks: list[tuple[int, Decimal]] = []

    partner_label = (
        f'P#{partner_filter_id}' if partner_filter_id else 'любой партнёр'
    )
    print(
        f'  orphan #{orphan.id} ({orphan.created_at.date()}, '
        f'store={store.name}, {partner_label}): amount={orphan.amount}, '
        f'кандидатов-заказов: {len(orders_list)}'
    )

    for order in orders_list:
        if remaining <= Decimal('0'):
            break
        outstanding = order.outstanding_debt
        if outstanding <= Decimal('0'):
            continue
        chunk = min(outstanding, remaining)
        distributed_chunks.append((order.id, chunk))
        remaining -= chunk

    if not distributed_chunks:
        problems.append(
            f'  ! orphan #{orphan.id} (store={store.name}, amount={orphan.amount}): '
            f'нет подходящих заказов — оставлен как есть'
        )
        stats['orphans_not_distributable'] += 1
        continue

    # Печатаем план
    for oid, ch in distributed_chunks:
        print(f'      → заказ #{oid}: +paid_amount={ch}')
    if remaining > Decimal('0'):
        print(f'      → остаётся в orphan: {remaining}')

    if APPLY:
        with transaction.atomic():
            for order_id, chunk in distributed_chunks:
                # Перечитываем заказ под select_for_update, чтобы исключить
                # параллельные изменения paid_amount.
                fresh = StoreOrder.objects.select_for_update().get(pk=order_id)
                fresh_outstanding = fresh.outstanding_debt
                # Сжимаем chunk до текущего outstanding (на случай конкурентных
                # платежей между планом и применением).
                actual_chunk = min(fresh_outstanding, chunk)
                if actual_chunk <= Decimal('0'):
                    # Заказ уже погашен полностью извне — пропускаем; остаток
                    # дораспределится логически на следующих итерациях
                    # (а если все заказы исчезли — останется в orphan).
                    continue
                received_by = orphan.received_by or fresh.partner
                new_payment = DebtPayment.objects.create(
                    order=fresh,
                    store=store,
                    amount=actual_chunk,
                    paid_by=orphan.paid_by,
                    received_by=received_by,
                    comment=(
                        f'{orphan_comment} {MARKER_PREFIX} #{orphan.id}]'
                    ).strip(),
                )
                # created_at в DebtPayment auto_now_add, обновляем отдельно,
                # чтобы дата платежа в отчётах не сместилась на «сегодня».
                DebtPayment.objects.filter(pk=new_payment.pk).update(
                    created_at=orphan.created_at,
                )
                StoreOrder.objects.filter(pk=fresh.pk).update(
                    paid_amount=F('paid_amount') + actual_chunk,
                )
                stats['payments_created'] += 1
                stats['amount_distributed'] += actual_chunk
                # Если actual_chunk < chunk (был race) — недостача уходит в
                # remaining через переоценку ниже.
                if actual_chunk < chunk:
                    remaining += (chunk - actual_chunk)

            # Помечаем orphan: amount = непогашенный остаток, comment с маркером
            if remaining > Decimal('0'):
                new_orphan_comment = (
                    f'{orphan_comment} {MARKER_PREFIX} #{orphan.id} '
                    f'частично, было={orphan.amount}, осталось={remaining}]'
                ).strip()
            else:
                new_orphan_comment = (
                    f'{orphan_comment} {MARKER_PREFIX} #{orphan.id} '
                    f'полностью, было={orphan.amount}]'
                ).strip()
            DebtPayment.objects.filter(pk=orphan.pk).update(
                amount=remaining,
                comment=new_orphan_comment,
            )
    else:
        # Dry-run: только учёт
        for _, ch in distributed_chunks:
            stats['payments_created'] += 1
            stats['amount_distributed'] += ch

    if remaining <= Decimal('0'):
        stats['orphans_distributed_fully'] += 1
    else:
        stats['orphans_distributed_partially'] += 1
        stats['amount_remaining_in_orphans'] += remaining

# ─── Итоги ──────────────────────────────────────────────────────
verb = 'создано' if APPLY else 'будет создано'
print('\n' + '=' * 78)
print('ИТОГО:')
print(f"  Orphan-платежей просмотрено:        {stats['orphans_seen']}")
print(f"  Пропущено (уже обработаны):         {stats['orphans_skipped_idempotent']}")
print(f"  Разнесено полностью:                {stats['orphans_distributed_fully']}")
print(f"  Разнесено частично:                 {stats['orphans_distributed_partially']}")
print(f"  Не разнесено (нет заказов):         {stats['orphans_not_distributable']}")
print(f"  Новых DebtPayment {verb}: {stats['payments_created']}")
print(f"  Сумма разнесена:                    {stats['amount_distributed']}")
print(f"  Остаётся в orphan-платежах:         {stats['amount_remaining_in_orphans']}")
if problems:
    print(f"\n  ПРОБЛЕМЫ ({len(problems)}):")
    for p in problems:
        print(p)
print('=' * 78)
if not APPLY:
    print('DRY-RUN завершён. Запусти с APPLY=1 для применения.')
print('=' * 78)
