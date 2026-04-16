"""
Регресс на pay_store_debt: после частичного/полного погашения
outstanding_debt у заказа должен корректно уменьшаться,
а повторная оплата сверх остатка — отбиваться 400.

Покрывает баг: pay-debt обнулял store.debt, но не трогал paid_amount у заказов,
из-за чего order.outstanding_debt оставался полным и ту же сумму собирали повторно.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from orders.models import DebtPayment, StoreOrder


PAY_DEBT_URL = '/api/stores/stores/{store_id}/pay-debt/'


def _pay_debt(user, store, amount):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.post(
        PAY_DEBT_URL.format(store_id=store.id),
        {'amount': str(amount)},
        format='json',
    )


def _outstanding(order: StoreOrder) -> Decimal:
    order.refresh_from_db()
    return max(order.debt_amount - order.paid_amount, Decimal('0'))


def test_full_pay_debt_zeros_order_outstanding(preorder, partner):
    """Полное погашение долга обнуляет outstanding_debt заказа."""
    store = preorder.store
    store.refresh_from_db()
    debt = store.debt
    assert debt > 0
    assert _outstanding(preorder) == preorder.debt_amount

    resp = _pay_debt(partner, store, debt)

    assert resp.status_code == 201, resp.data
    store.refresh_from_db()
    assert store.debt == Decimal('0')
    assert _outstanding(preorder) == Decimal('0')


def test_partial_pay_debt_reduces_order_outstanding(preorder, partner):
    """Частичное погашение уменьшает outstanding_debt заказа на ту же сумму."""
    store = preorder.store
    store.refresh_from_db()
    half = (store.debt / Decimal('2')).quantize(Decimal('0.01'))
    initial_outstanding = _outstanding(preorder)

    resp = _pay_debt(partner, store, half)

    assert resp.status_code == 201, resp.data
    assert _outstanding(preorder) == initial_outstanding - half


def test_second_pay_after_full_rejected(preorder, partner):
    """
    Главный регресс: повторная оплата после полного погашения падает 400,
    а не проходит с созданием дубликата DebtPayment.
    """
    store = preorder.store
    store.refresh_from_db()
    debt = store.debt

    first = _pay_debt(partner, store, debt)
    assert first.status_code == 201
    payments_after_first = DebtPayment.objects.filter(store=store).count()

    second = _pay_debt(partner, store, debt)

    assert second.status_code == 400
    assert DebtPayment.objects.filter(store=store).count() == payments_after_first
    assert 'превышает' in str(second.data).lower() or 'долг' in str(second.data).lower()
