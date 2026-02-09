import os
from decimal import Decimal
from typing import Dict, Any

import pytest

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('FORCE_SQLITE', 'True')

import django  # noqa: E402

django.setup()

from django.db.models import Q  # noqa: E402
from users.models import User  # noqa: E402
from stores.models import (  # noqa: E402
    Store,
    Region,
    City,
    PartnerInventory,
    StoreInventory,
)
from products.models import (  # noqa: E402
    Product,
    PartnerExpense,
    Expense,
    ProductRecipe,
    ProductionBatch,
)
from orders.models import (  # noqa: E402
    StoreOrder,
    StoreOrderItem,
    StoreOrderStatus,
    DebtPayment,
    ReturnedItem,
    DefectiveProduct,
)
from orders.services import OrderWorkflowService, BasketService  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_database() -> None:
    """Удаляет тестовые данные, созданные системными тестами."""
    name_filter = (
        Q(name__contains='ТЕСТ') |
        Q(name__contains='Тест') |
        Q(name__contains='тест')
    )
    DefectiveProduct.objects.all().delete()
    ReturnedItem.objects.all().delete()
    DebtPayment.objects.all().delete()
    StoreOrderItem.objects.all().delete()
    StoreOrder.objects.all().delete()
    StoreInventory.objects.all().delete()
    PartnerInventory.objects.all().delete()
    PartnerExpense.objects.all().delete()
    ProductRecipe.objects.all().delete()
    ProductionBatch.objects.all().delete()
    Expense.objects.filter(name_filter).delete()
    Product.objects.filter(name_filter).delete()
    Store.objects.filter(name_filter).delete()
    City.objects.filter(name_filter).delete()
    Region.objects.filter(name_filter).delete()
    User.objects.filter(phone__startswith='+996700').delete()


def _create_users() -> Dict[str, User]:
    admin = User.objects.create(
        phone='+996700000001',
        email='admin@test.local',
        name='Админ',
        second_name='ТЕСТ',
        role='admin',
        is_staff=True,
        is_superuser=True,
    )
    admin.set_password('admin123')
    admin.save()

    partner = User.objects.create(
        phone='+996700000002',
        email='partner@test.local',
        name='Партнёр',
        second_name='ТЕСТ',
        role='partner',
    )
    partner.set_password('partner123')
    partner.save()

    store_user = User.objects.create(
        phone='+996700000003',
        email='store@test.local',
        name='Магазин',
        second_name='ТЕСТ',
        role='store',
    )
    store_user.set_password('store123')
    store_user.save()

    return {'admin': admin, 'partner': partner, 'store_user': store_user}


def _create_store(store_user: User) -> Store:
    region, _ = Region.objects.get_or_create(name='ТЕСТ Регион')
    city, _ = City.objects.get_or_create(region=region, name='ТЕСТ Город')
    inn = f"1234567{store_user.id:05d}"  # гарантированно уникальный для тестов
    return Store.objects.create(
        name='ТЕСТ Магазин Айсберг',
        owner=store_user,
        region=region,
        city=city,
        address='ул. Тестовая, 1',
        inn=inn,
        owner_name='Магазин ТЕСТ',
        phone='+996555111222',
        approval_status='approved',
        is_active=True,
    )


def _create_products() -> Dict[str, Product]:
    products = {
        'ice_cream': Product.objects.create(
            name='ТЕСТ Мороженое Пломбир',
            manual_price=Decimal('100.00'),
            stock_quantity=Decimal('1000'),
            is_available=True,
            is_weight_based=False,
            is_bonus=True,
        ),
        'juice': Product.objects.create(
            name='ТЕСТ Сок Яблочный',
            manual_price=Decimal('50.00'),
            stock_quantity=Decimal('500'),
            is_available=True,
            is_weight_based=False,
            is_bonus=False,
        ),
        'cheese': Product.objects.create(
            name='ТЕСТ Сыр Брынза (весовой)',
            manual_price=Decimal('800.00'),
            stock_quantity=Decimal('50'),
            is_available=True,
            is_weight_based=True,
            is_bonus=False,
        ),
        'meat': Product.objects.create(
            name='ТЕСТ Мясо Говядина (весовой)',
            manual_price=Decimal('650.00'),
            stock_quantity=Decimal('100'),
            is_available=True,
            is_weight_based=True,
            is_bonus=False,
        ),
    }
    return products


def _create_partner_inventory(partner: User, products: Dict[str, Product]) -> None:
    for product in products.values():
        qty = Decimal('50') if product.is_weight_based else Decimal('100')
        PartnerInventory.objects.create(
            partner=partner,
            product=product,
            quantity=qty,
            reserved_quantity=Decimal('0'),
        )


def _create_preorder(data: Dict[str, Any]) -> StoreOrder:
    partner = data['partner']
    store_user = data['store_user']
    store = data['store']
    products = data['products']

    order = StoreOrder.objects.create(
        order_type='preorder',
        store=store,
        created_by=store_user,
        status=StoreOrderStatus.PENDING,
    )

    for product_name, quantity in [
        ('ice_cream', Decimal('10')),
        ('juice', Decimal('5')),
        ('cheese', Decimal('2.5')),
    ]:
        product = products[product_name]
        StoreOrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            price=product.final_price,
        )

    order.calculate_total()
    order.save()

    OrderWorkflowService.admin_approve_order(order=order, admin_user=partner)
    BasketService.confirm_basket(
        store=store,
        partner_user=partner,
        prepayment_amount=Decimal('1000'),
    )
    order.refresh_from_db()
    store.refresh_from_db()
    return order


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_state():
    """Глобальная очистка перед/после каждого теста."""
    _clean_database()
    yield
    _clean_database()


@pytest.fixture()
def base_data(clean_state) -> Dict[str, Any]:
    """Готовит пользователей, магазин и товары для тестов."""
    users = _create_users()
    store = _create_store(users['store_user'])
    products = _create_products()
    _create_partner_inventory(users['partner'], products)
    return {**users, 'store': store, 'products': products}


@pytest.fixture(autouse=True)
def ensure_base_data(base_data):
    """Автоматически создаёт базовые данные для тестов без фикстур."""
    return


@pytest.fixture()
def admin(base_data):
    return base_data['admin']


@pytest.fixture()
def partner(base_data):
    return base_data['partner']


@pytest.fixture()
def store_user(base_data):
    return base_data['store_user']


@pytest.fixture()
def store(base_data):
    return base_data['store']


@pytest.fixture()
def products(base_data):
    return base_data['products']


@pytest.fixture()
def ice_cream(products):
    return products['ice_cream']


@pytest.fixture()
def juice(products):
    return products['juice']


@pytest.fixture()
def cheese(products):
    return products['cheese']


@pytest.fixture()
def meat(products):
    return products['meat']


@pytest.fixture()
def preorder(base_data):
    return _create_preorder(base_data)
