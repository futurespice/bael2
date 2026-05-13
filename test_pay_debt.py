"""
Регресс на pay_store_debt (FIFO-модель):
платёж раздаётся по ACCEPTED заказам магазина (старые первыми),
синхронизируя Order.paid_amount со Store.debt. Если заказов на покрытие
не хватает, остаток создаётся как orphan-DebtPayment (best-effort).
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from orders.models import DebtPayment


PAY_DEBT_URL = '/api/stores/stores/{store_id}/pay-debt/'


def _pay_debt(user, store, amount):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.post(
        PAY_DEBT_URL.format(store_id=store.id),
        {'amount': str(amount)},
        format='json',
    )


def test_full_pay_debt_zeros_store_debt(preorder, partner):
    """Полное погашение обнуляет Store.debt и привязывает DebtPayment к заказу."""
    store = preorder.store
    store.refresh_from_db()
    debt = store.debt
    assert debt > 0

    resp = _pay_debt(partner, store, debt)

    assert resp.status_code == 201, resp.data
    store.refresh_from_db()
    assert store.debt == Decimal('0')
    assert store.total_paid == debt

    payment = DebtPayment.objects.get(store=store)
    assert payment.amount == debt
    assert payment.received_by_id == partner.id
    # FIFO привязывает платёж к заказу (а не создаёт orphan):
    assert payment.order_id == preorder.id

    # Order.paid_amount синхронизирован со Store.debt:
    preorder.refresh_from_db()
    assert preorder.outstanding_debt == Decimal('0')


def test_partial_pay_debt_reduces_store_debt(preorder, partner):
    """Частичное погашение уменьшает Store.debt ровно на сумму."""
    store = preorder.store
    store.refresh_from_db()
    debt_before = store.debt
    half = (debt_before / Decimal('2')).quantize(Decimal('0.01'))

    resp = _pay_debt(partner, store, half)

    assert resp.status_code == 201, resp.data
    store.refresh_from_db()
    assert store.debt == debt_before - half
    assert store.total_paid == half


def test_pay_more_than_debt_rejected(preorder, partner):
    """Сумма больше долга → 400, состояние не меняется."""
    store = preorder.store
    store.refresh_from_db()
    debt = store.debt

    resp = _pay_debt(partner, store, debt + Decimal('1'))

    assert resp.status_code == 400
    store.refresh_from_db()
    assert store.debt == debt
    assert DebtPayment.objects.filter(store=store).count() == 0


def test_full_cycle_prepayment_then_pay_debt(preorder, partner):
    """
    Интеграция предоплаты и pay-debt:
    confirm_basket с предоплатой 1000 → Store.debt = total - 1000
    pay-debt(part) → Store.debt уменьшается, total_paid растёт
    pay-debt(остаток) → Store.debt = 0
    Предоплата осталась на заказе и не учитывается в total_paid.
    """
    store = preorder.store
    preorder.refresh_from_db()
    store.refresh_from_db()

    assert preorder.prepayment_amount == Decimal('1000')
    assert preorder.debt_amount == preorder.total_amount - Decimal('1000')
    assert store.debt == preorder.debt_amount
    assert store.total_paid == Decimal('0')

    debt_initial = store.debt
    part = (debt_initial / Decimal('2')).quantize(Decimal('0.01'))

    resp1 = _pay_debt(partner, store, part)
    assert resp1.status_code == 201
    store.refresh_from_db()
    assert store.debt == debt_initial - part
    assert store.total_paid == part

    resp2 = _pay_debt(partner, store, store.debt)
    assert resp2.status_code == 201
    store.refresh_from_db()
    assert store.debt == Decimal('0')
    assert store.total_paid == debt_initial

    preorder.refresh_from_db()
    assert preorder.prepayment_amount == Decimal('1000')
    assert DebtPayment.objects.filter(store=store).count() == 2


def test_second_pay_after_full_rejected(preorder, partner):
    """Повторная оплата после полного погашения → 400, без дубликата."""
    store = preorder.store
    store.refresh_from_db()
    debt = store.debt

    first = _pay_debt(partner, store, debt)
    assert first.status_code == 201

    second = _pay_debt(partner, store, debt)

    assert second.status_code == 400
    assert DebtPayment.objects.filter(store=store).count() == 1


def test_pay_debt_keeps_reports_in_sync_with_store_debt(preorder, partner, admin):
    """
    После /pay-debt/ долг в /api/reports/statistics/ совпадает со Store.debt.
    Это главный регрессионный тест: раньше orphan-DebtPayment уменьшал
    Store.debt, но не Order.paid_amount → формула отчёта расходилась.
    """
    store = preorder.store
    store.refresh_from_db()
    debt_before = store.debt
    assert debt_before > 0

    # Частичное гашение
    part = (debt_before / Decimal('2')).quantize(Decimal('0.01'))
    resp = _pay_debt(partner, store, part)
    assert resp.status_code == 201, resp.data

    store.refresh_from_db()
    expected_debt = store.debt
    assert expected_debt == debt_before - part

    # Админский /reports/statistics/ должен показывать тот же долг
    client = APIClient()
    client.force_authenticate(user=admin)
    stats_resp = client.get('/api/reports/statistics/?period=all_time')
    assert stats_resp.status_code == 200, stats_resp.data
    reported_debt = Decimal(str(stats_resp.data['statistics']['debt']))
    assert reported_debt == expected_debt, (
        f'Отчёт показывает debt={reported_debt}, '
        f'а Store.debt={expected_debt} — рассинхрон не устранён'
    )

    # Партнёрский /reports/partners/statistics/ — то же.
    # Этот эндпоинт принимает только day/week/month/year, period=year
    # покрывает текущий заказ (confirmed_at=today).
    client.force_authenticate(user=partner)
    pstats_resp = client.get('/api/reports/partners/statistics/?period=year')
    assert pstats_resp.status_code == 200, pstats_resp.data
    reported_pdebt = Decimal(pstats_resp.data['debt'])
    assert reported_pdebt == expected_debt, (
        f'Партнёрский отчёт показывает debt={reported_pdebt}, '
        f'а Store.debt={expected_debt}'
    )


def test_pay_debt_fifo_across_multiple_orders(
    store, partner, admin, ice_cream
):
    """
    Два ACCEPTED заказа одного партнёра, платёж покрывает первый
    целиком + часть второго. FIFO порядок — по confirmed_at ASC.
    """
    from datetime import timedelta
    from django.utils import timezone
    from orders.models import (
        StoreOrder, StoreOrderItem, StoreOrderStatus, StoreOrderType,
    )

    now = timezone.now()
    order_old = StoreOrder.objects.create(
        store=store,
        partner=partner,
        status=StoreOrderStatus.ACCEPTED,
        order_type=StoreOrderType.MANUAL,
        total_amount=Decimal('100.00'),
        prepayment_amount=Decimal('0'),
        debt_amount=Decimal('100.00'),
        paid_amount=Decimal('0'),
        confirmed_at=now - timedelta(days=2),
        confirmed_by=partner,
    )
    order_new = StoreOrder.objects.create(
        store=store,
        partner=partner,
        status=StoreOrderStatus.ACCEPTED,
        order_type=StoreOrderType.MANUAL,
        total_amount=Decimal('200.00'),
        prepayment_amount=Decimal('0'),
        debt_amount=Decimal('200.00'),
        paid_amount=Decimal('0'),
        confirmed_at=now,
        confirmed_by=partner,
    )
    # Store.debt = 300 (как если бы оба заказа прошли confirm_basket)
    from django.db.models import F
    from stores.models import Store
    Store.objects.filter(pk=store.pk).update(debt=F('debt') + Decimal('300'))

    # Платим 150: целиком покрывает старый (100) + 50 от нового
    resp = _pay_debt(partner, store, Decimal('150'))
    assert resp.status_code == 201, resp.data

    order_old.refresh_from_db()
    order_new.refresh_from_db()
    assert order_old.paid_amount == Decimal('100.00')
    assert order_old.outstanding_debt == Decimal('0.00')
    assert order_new.paid_amount == Decimal('50.00')
    assert order_new.outstanding_debt == Decimal('150.00')

    # Создалось ровно 2 DebtPayment, оба привязаны к заказам
    payments = DebtPayment.objects.filter(store=store).order_by('id')
    assert payments.count() == 2
    assert payments[0].order_id == order_old.id
    assert payments[0].amount == Decimal('100.00')
    assert payments[1].order_id == order_new.id
    assert payments[1].amount == Decimal('50.00')


def test_pay_debt_admin_filters_by_partner_id(
    store, partner, partner2, admin, ice_cream
):
    """
    Магазин с заказами от двух партнёров. Админ платит с partner_id=P1 —
    FIFO применяется ТОЛЬКО к заказам P1, заказы P2 не трогаются.
    """
    from django.utils import timezone
    from orders.models import (
        StoreOrder, StoreOrderStatus, StoreOrderType,
    )

    now = timezone.now()
    order_p1 = StoreOrder.objects.create(
        store=store, partner=partner,
        status=StoreOrderStatus.ACCEPTED,
        order_type=StoreOrderType.MANUAL,
        total_amount=Decimal('100'),
        prepayment_amount=Decimal('0'),
        debt_amount=Decimal('100'),
        paid_amount=Decimal('0'),
        confirmed_at=now, confirmed_by=partner,
    )
    order_p2 = StoreOrder.objects.create(
        store=store, partner=partner2,
        status=StoreOrderStatus.ACCEPTED,
        order_type=StoreOrderType.MANUAL,
        total_amount=Decimal('200'),
        prepayment_amount=Decimal('0'),
        debt_amount=Decimal('200'),
        paid_amount=Decimal('0'),
        confirmed_at=now, confirmed_by=partner2,
    )
    from django.db.models import F
    from stores.models import Store
    Store.objects.filter(pk=store.pk).update(debt=F('debt') + Decimal('300'))

    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post(
        PAY_DEBT_URL.format(store_id=store.id),
        {'amount': '100', 'partner_id': partner.id},
        format='json',
    )
    assert resp.status_code == 201, resp.data

    order_p1.refresh_from_db()
    order_p2.refresh_from_db()
    # Заказ P1 закрыт, P2 не тронут
    assert order_p1.outstanding_debt == Decimal('0')
    assert order_p2.outstanding_debt == Decimal('200')

    # Привязанный платёж создан с received_by = P1
    payment = DebtPayment.objects.get(store=store, order=order_p1)
    assert payment.received_by_id == partner.id


def test_pay_debt_creates_orphan_when_no_orders(store, partner):
    """
    Store.debt выставлен вручную, ACCEPTED заказов нет → FIFO не находит куда
    разносить → создаётся orphan-DebtPayment (back-compat для аварийного
    случая, как до фикса).
    """
    from django.db.models import F
    from stores.models import Store
    Store.objects.filter(pk=store.pk).update(debt=F('debt') + Decimal('500'))
    store.refresh_from_db()

    resp = _pay_debt(partner, store, Decimal('200'))
    assert resp.status_code == 201, resp.data

    payment = DebtPayment.objects.get(store=store)
    assert payment.order_id is None  # orphan-fallback сработал
    assert payment.amount == Decimal('200')
    assert payment.received_by_id == partner.id

    store.refresh_from_db()
    assert store.debt == Decimal('300')
