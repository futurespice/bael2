"""
Тесты для новых фич:
1. Дополнительные цены (AdditionalPrice)
2. Долги партнёра (partner-debts)
3. Оплата долга админом (pay-debt с partner_id)
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('FORCE_SQLITE', 'True')

import django
django.setup()

import pytest
from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework import status

from users.models import User
from products.models import Product, AdditionalPrice
from stores.models import Store, Region, City, PartnerInventory
from orders.models import StoreOrder, StoreOrderItem, StoreOrderStatus, DebtPayment


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture(autouse=True)
def clean_db():
    """Очистка перед каждым тестом."""
    AdditionalPrice.objects.all().delete()
    DebtPayment.objects.all().delete()
    StoreOrderItem.objects.all().delete()
    StoreOrder.objects.all().delete()
    PartnerInventory.objects.all().delete()
    yield
    AdditionalPrice.objects.all().delete()
    DebtPayment.objects.all().delete()
    StoreOrderItem.objects.all().delete()
    StoreOrder.objects.all().delete()
    PartnerInventory.objects.all().delete()


@pytest.fixture
def admin_user():
    user, _ = User.objects.get_or_create(
        phone='+996700099001',
        defaults={
            'email': 'newadmin@test.local',
            'name': 'НовыйАдмин',
            'second_name': 'ТЕСТ',
            'role': 'admin',
            'is_staff': True,
        }
    )
    user.set_password('admin123')
    user.save()
    return user


@pytest.fixture
def partner_user():
    user, _ = User.objects.get_or_create(
        phone='+996700099002',
        defaults={
            'email': 'newpartner@test.local',
            'name': 'НовыйПартнёр',
            'second_name': 'ТЕСТ',
            'role': 'partner',
        }
    )
    user.set_password('partner123')
    user.save()
    return user


@pytest.fixture
def partner2_user():
    user, _ = User.objects.get_or_create(
        phone='+996700099003',
        defaults={
            'email': 'newpartner2@test.local',
            'name': 'Партнёр2',
            'second_name': 'ТЕСТ',
            'role': 'partner',
        }
    )
    user.set_password('partner2pw')
    user.save()
    return user


@pytest.fixture
def store_user():
    user, _ = User.objects.get_or_create(
        phone='+996700099004',
        defaults={
            'email': 'newstore@test.local',
            'name': 'НовыйМагазин',
            'second_name': 'ТЕСТ',
            'role': 'store',
        }
    )
    user.set_password('store123')
    user.save()
    return user


@pytest.fixture
def region():
    r, _ = Region.objects.get_or_create(name='ТЕСТ РегионДопЦена')
    return r


@pytest.fixture
def city(region):
    c, _ = City.objects.get_or_create(name='ТЕСТ ГородДопЦена', region=region)
    return c


@pytest.fixture
def store(store_user, region, city):
    s, _ = Store.objects.get_or_create(
        inn='123456789012',
        defaults={
            'name': 'ТЕСТ МагазинДопЦена',
            'owner_name': 'Тест',
            'phone': '+996700099010',
            'owner': store_user,
            'address': 'ТестАдрес',
            'region': region,
            'city': city,
            'is_active': True,
        }
    )
    return s


@pytest.fixture
def product():
    p, _ = Product.objects.get_or_create(
        name='ТЕСТ ТоварДопЦена',
        defaults={
            'unit': 'piece',
            'is_weight_based': False,
            'is_bonus': False,
            'final_price': Decimal('100.00'),
            'manual_price': Decimal('100.00'),
            'stock_quantity': Decimal('1000'),
        }
    )
    return p


@pytest.fixture
def bonus_product():
    p, _ = Product.objects.get_or_create(
        name='ТЕСТ БонусТоварДопЦена',
        defaults={
            'unit': 'piece',
            'is_weight_based': False,
            'is_bonus': True,
            'final_price': Decimal('50.00'),
            'manual_price': Decimal('50.00'),
            'stock_quantity': Decimal('1000'),
        }
    )
    return p


@pytest.fixture
def admin_client(admin_user):
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


@pytest.fixture
def partner_client(partner_user):
    c = APIClient()
    c.force_authenticate(user=partner_user)
    return c


@pytest.fixture
def partner2_client(partner2_user):
    c = APIClient()
    c.force_authenticate(user=partner2_user)
    return c


# ===========================================================================
# 1. ТЕСТЫ ДОП ЦЕН
# ===========================================================================

class TestAdditionalPriceModel:
    """Тесты модели AdditionalPrice."""

    def test_create_additional_price(self, product):
        ap = AdditionalPrice.objects.create(
            product=product,
            name='Цена для Ош',
            price=Decimal('120.00'),
        )
        assert ap.pk is not None
        assert ap.name == 'Цена для Ош'
        assert ap.price == Decimal('120.00')
        assert ap.is_active is True

    def test_multiple_additional_prices(self, product):
        ap1 = AdditionalPrice.objects.create(product=product, name='Ош', price=Decimal('120'))
        ap2 = AdditionalPrice.objects.create(product=product, name='Жалал-Абад', price=Decimal('130'))
        ap3 = AdditionalPrice.objects.create(product=product, name='Нарын', price=Decimal('140'))
        assert product.additional_prices.count() == 3

    def test_cascade_delete(self, product):
        AdditionalPrice.objects.create(product=product, name='Тест', price=Decimal('100'))
        product_id = product.id
        assert AdditionalPrice.objects.filter(product_id=product_id).count() == 1
        product.delete()
        assert AdditionalPrice.objects.filter(product_id=product_id).count() == 0


class TestAdditionalPriceAPI:
    """Тесты API доп цен через ProductViewSet."""

    def test_create_product_with_additional_prices(self, admin_client):
        data = {
            'name': 'ТЕСТ ТоварСДопЦеной',
            'unit': 'piece',
            'is_weight_based': False,
            'is_bonus': False,
            'manual_price': '100.00',
            'additional_prices': [
                {'name': 'Ош', 'price': '120.00'},
                {'name': 'Нарын', 'price': '140.00'},
            ],
        }
        resp = admin_client.post('/api/products/products/', data, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert len(resp.data['additional_prices']) == 2
        names = {ap['name'] for ap in resp.data['additional_prices']}
        assert names == {'Ош', 'Нарын'}
        # Cleanup
        Product.objects.filter(name='ТЕСТ ТоварСДопЦеной').delete()

    def test_update_product_additional_prices(self, admin_client, product):
        # Создаём доп цены
        ap1 = AdditionalPrice.objects.create(product=product, name='Старая', price=Decimal('110'))

        data = {
            'additional_prices': [
                {'id': ap1.id, 'name': 'Обновлённая', 'price': '115.00'},
                {'name': 'Новая', 'price': '130.00'},
            ],
        }
        resp = admin_client.patch(
            f'/api/products/products/{product.id}/',
            data, format='json',
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        ap_names = {ap['name'] for ap in resp.data['additional_prices']}
        assert ap_names == {'Обновлённая', 'Новая'}
        # Старая обновилась, а не удалилась
        assert AdditionalPrice.objects.filter(pk=ap1.id).exists()
        ap1.refresh_from_db()
        assert ap1.name == 'Обновлённая'
        assert ap1.price == Decimal('115.00')

    def test_delete_additional_prices_on_update(self, admin_client, product):
        ap1 = AdditionalPrice.objects.create(product=product, name='Удалится', price=Decimal('110'))
        ap2 = AdditionalPrice.objects.create(product=product, name='Останется', price=Decimal('120'))

        # Отправляем только ap2 — ap1 должна удалиться
        data = {
            'additional_prices': [
                {'id': ap2.id, 'name': 'Останется', 'price': '120.00'},
            ],
        }
        resp = admin_client.patch(
            f'/api/products/products/{product.id}/',
            data, format='json',
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data['additional_prices']) == 1
        assert not AdditionalPrice.objects.filter(pk=ap1.id).exists()

    def test_product_list_includes_additional_prices(self, admin_client, product):
        AdditionalPrice.objects.create(product=product, name='Ош', price=Decimal('120'))
        resp = admin_client.get('/api/products/products/')
        assert resp.status_code == status.HTTP_200_OK
        # Ищем наш продукт
        our_product = None
        for p in resp.data['results']:
            if p['id'] == product.id:
                our_product = p
                break
        assert our_product is not None
        assert len(our_product['additional_prices']) == 1
        assert our_product['additional_prices'][0]['name'] == 'Ош'


class TestManualOrderWithAdditionalPrice:
    """Тесты ручного заказа с доп ценой."""

    def test_manual_order_with_additional_price(self, partner_client, partner_user, store, product):
        # Создаём доп цену
        ap = AdditionalPrice.objects.create(product=product, name='Ош', price=Decimal('150.00'))

        # Создаём инвентарь партнёра
        PartnerInventory.objects.create(
            partner=partner_user, product=product, quantity=Decimal('100'),
        )

        data = {
            'store': store.id,
            'items': [
                {
                    'product': product.id,
                    'quantity': 10,
                    'additional_price_id': ap.id,
                },
            ],
            'prepayment': 0,
        }
        resp = partner_client.post('/api/orders/partners/manual-orders/', data, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data

        # Проверяем что цена = доп цена (150), а не final_price (100)
        order = StoreOrder.objects.get(pk=resp.data['id'])
        item = order.items.filter(is_bonus=False).first()
        assert item.price == Decimal('150.00')
        assert order.total_amount == Decimal('1500.00')  # 10 × 150

    def test_manual_order_additional_price_not_bonus(self, partner_client, partner_user, store, bonus_product):
        """Товар с доп ценой не может быть бонусным."""
        ap = AdditionalPrice.objects.create(
            product=bonus_product, name='Ош', price=Decimal('80.00'),
        )
        PartnerInventory.objects.create(
            partner=partner_user, product=bonus_product, quantity=Decimal('100'),
        )
        data = {
            'store': store.id,
            'items': [
                {
                    'product': bonus_product.id,
                    'quantity': 10,
                    'additional_price_id': ap.id,
                    'is_bonus': True,
                },
            ],
            'prepayment': 0,
        }
        resp = partner_client.post('/api/orders/partners/manual-orders/', data, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_manual_order_wrong_product_additional_price(self, partner_client, partner_user, store, product):
        """Доп цена другого товара не подходит."""
        other_product = Product.objects.create(
            name='ТЕСТ ДругойТовар',
            unit='piece',
            final_price=Decimal('200.00'),
            manual_price=Decimal('200.00'),
            stock_quantity=Decimal('100'),
        )
        ap = AdditionalPrice.objects.create(
            product=other_product, name='Другой', price=Decimal('250.00'),
        )
        PartnerInventory.objects.create(
            partner=partner_user, product=product, quantity=Decimal('100'),
        )
        data = {
            'store': store.id,
            'items': [
                {
                    'product': product.id,
                    'quantity': 5,
                    'additional_price_id': ap.id,
                },
            ],
            'prepayment': 0,
        }
        resp = partner_client.post('/api/orders/partners/manual-orders/', data, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        other_product.delete()

    def test_manual_order_without_additional_price(self, partner_client, partner_user, store, product):
        """Обычный ручной заказ без доп цены — использует final_price."""
        PartnerInventory.objects.create(
            partner=partner_user, product=product, quantity=Decimal('100'),
        )
        data = {
            'store': store.id,
            'items': [
                {'product': product.id, 'quantity': 5},
            ],
            'prepayment': 0,
        }
        resp = partner_client.post('/api/orders/partners/manual-orders/', data, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        order = StoreOrder.objects.get(pk=resp.data['id'])
        item = order.items.filter(is_bonus=False).first()
        assert item.price == product.final_price


# ===========================================================================
# 2. ТЕСТЫ ДОЛГОВ ПАРТНЁРА
# ===========================================================================

class TestPartnerDebts:
    """Тесты эндпоинтов долгов партнёра."""

    def _create_accepted_order(self, partner, store, total, prepayment=Decimal('0')):
        """Создаёт accepted заказ."""
        from django.utils import timezone
        order = StoreOrder.objects.create(
            store=store,
            partner=partner,
            status=StoreOrderStatus.ACCEPTED,
            order_type='manual',
            total_amount=total,
            prepayment_amount=prepayment,
            debt_amount=total - prepayment,
            confirmed_by=partner,
            confirmed_at=timezone.now(),
        )
        return order

    def test_partner_sees_own_debts(self, partner_client, partner_user, store):
        self._create_accepted_order(partner_user, store, Decimal('1000'), Decimal('200'))
        resp = partner_client.get('/api/stores/partner-debts/')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]['store_id'] == store.id
        assert resp.data[0]['total_orders_amount'] == 1000.0
        assert resp.data[0]['total_prepayment'] == 200.0
        assert resp.data[0]['outstanding_debt'] == 800.0

    def test_partner_does_not_see_other_partner_debts(
        self, partner_client, partner_user, partner2_user, store
    ):
        # Заказ partner2 — partner не должен видеть
        self._create_accepted_order(partner2_user, store, Decimal('500'))
        resp = partner_client.get('/api/stores/partner-debts/')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 0

    def test_admin_sees_all_debts(self, admin_client, partner_user, partner2_user, store):
        self._create_accepted_order(partner_user, store, Decimal('1000'))
        self._create_accepted_order(partner2_user, store, Decimal('500'))
        resp = admin_client.get('/api/stores/partner-debts/')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1  # 1 магазин, но сумма общая
        assert resp.data[0]['total_orders_amount'] == 1500.0

    def test_admin_filter_by_partner(self, admin_client, partner_user, partner2_user, store):
        self._create_accepted_order(partner_user, store, Decimal('1000'))
        self._create_accepted_order(partner2_user, store, Decimal('500'))
        resp = admin_client.get(f'/api/stores/partner-debts/?partner_id={partner_user.id}')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]['total_orders_amount'] == 1000.0

    def test_detail_endpoint(self, partner_client, partner_user, store):
        self._create_accepted_order(partner_user, store, Decimal('1000'), Decimal('200'))
        resp = partner_client.get(f'/api/stores/partner-debts/{store.id}/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['total_orders_amount'] == 1000.0
        assert resp.data['total_prepayment'] == 200.0
        assert resp.data['outstanding_debt'] == 800.0
        assert resp.data['store']['id'] == store.id

    def test_zero_debt_hidden_by_default(self, partner_client, partner_user, store):
        # Полностью оплаченный заказ
        self._create_accepted_order(partner_user, store, Decimal('500'), Decimal('500'))
        resp = partner_client.get('/api/stores/partner-debts/')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 0  # 0 долг — скрыт

    def test_show_all_includes_zero_debt(self, partner_client, partner_user, store):
        self._create_accepted_order(partner_user, store, Decimal('500'), Decimal('500'))
        resp = partner_client.get('/api/stores/partner-debts/?show_all=true')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1


# ===========================================================================
# 3. ТЕСТЫ ОПЛАТЫ ДОЛГА АДМИНОМ
# ===========================================================================

class TestPayDebt:
    """Тесты погашения долга магазина (pay-debt)."""

    def _setup_store_debt(self, store, amount):
        """Устанавливаем долг магазина."""
        from django.db.models import F
        Store.objects.filter(pk=store.pk).update(debt=F('debt') + amount)
        store.refresh_from_db()

    def test_partner_pay_debt(self, partner_client, partner_user, store):
        """Партнёр погашает долг — received_by = сам партнёр, order = None."""
        self._setup_store_debt(store, Decimal('1000'))

        resp = partner_client.post(
            f'/api/stores/stores/{store.id}/pay-debt/',
            {'amount': 300, 'comment': 'Оплата'},
            format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data

        payment = DebtPayment.objects.last()
        assert payment.order is None         # не привязан к заказу
        assert payment.store == store        # привязан к магазину
        assert payment.paid_by == partner_user
        assert payment.received_by == partner_user  # сам себе
        assert payment.amount == Decimal('300')

        store.refresh_from_db()
        assert store.debt == Decimal('700')

    def test_admin_pay_debt_with_partner_id(
        self, admin_client, admin_user, partner_user, store
    ):
        """Админ погашает долг с указани��м партнёра-получателя."""
        self._setup_store_debt(store, Decimal('1000'))

        resp = admin_client.post(
            f'/api/stores/stores/{store.id}/pay-debt/',
            {'amount': 300, 'partner_id': partner_user.id, 'comment': 'За партнёра'},
            format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data

        payment = DebtPayment.objects.last()
        assert payment.received_by == partner_user
        assert payment.paid_by == admin_user
        assert payment.order is None
        assert payment.store == store

    def test_admin_pay_debt_without_partner_id(
        self, admin_client, admin_user, store
    ):
        """Админ погашает общий долг магазина без привязки к партнёру."""
        self._setup_store_debt(store, Decimal('1000'))

        resp = admin_client.post(
            f'/api/stores/stores/{store.id}/pay-debt/',
            {'amount': 200},
            format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED
        payment = DebtPayment.objects.last()
        assert payment.received_by is None
        assert payment.order is None
        assert payment.store == store
        assert payment.amount == Decimal('200')

    def test_admin_pay_debt_invalid_partner(self, admin_client, store):
        self._setup_store_debt(store, Decimal('1000'))
        resp = admin_client.post(
            f'/api/stores/stores/{store.id}/pay-debt/',
            {'amount': 100, 'partner_id': 99999},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_pay_debt_exceeds_store_debt(self, partner_client, store):
        """Нельзя погасить ��ольше чем долг."""
        self._setup_store_debt(store, Decimal('100'))
        resp = partner_client.post(
            f'/api/stores/stores/{store.id}/pay-debt/',
            {'amount': 500},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
