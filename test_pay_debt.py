"""
Регресс на pay_store_debt (упрощённая модель v3.0):
долг живёт только на Store.debt; pay-debt уменьшает Store.debt и создаёт
DebtPayment, не трогая StoreOrder.paid_amount.
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
    """Полное погашение обнуляет Store.debt и создаёт DebtPayment."""
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
    assert payment.order_id is None


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
