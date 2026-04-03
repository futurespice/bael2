"""
conftest.py — Полные тестовые данные БайЭл (A → Z)
===================================================
Покрывает ВСЕ модули и сценарии:
  - Пользователи (admin, partner, store, partner2, store2)
  - География (регионы, города)
  - Магазины (2 магазина с разными состояниями)
  - Расходы: Physical Suzerain + Physical Civilian + Overhead
  - Товары: штучные (с/без бонуса) + весовые
  - Рецепты (ProductRecipe)
  - Партии производства (ProductionBatch)
  - Инвентарь партнёра (PartnerInventory)
  - Заказы: preorder → approve → confirm (полный цикл)
  - Дефекты, возвраты, платежи (DebtPayment)
  - Расходы партнёра (PartnerExpense)
"""
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
    ExpenseType,
    ExpenseStatus,
    ExpenseState,
    ApplyType,
    ExpenseUnitType,
)
from orders.models import (  # noqa: E402
    StoreOrder,
    StoreOrderItem,
    StoreOrderStatus,
    DebtPayment,
    ReturnedItem,
    DefectiveProduct,
)
from orders.services import OrderWorkflowService  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402


# ---------------------------------------------------------------------------
# Утилиты очистки
# ---------------------------------------------------------------------------

def _clean_database() -> None:
    """
    Удаляет ВСЕ тестовые данные перед/после каждого теста.
    Удаляет записи с префиксом ТЕСТ, а также все связанные объекты
    (заказы, инвентарь, рецепты) независимо от имени.
    """
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


def _full_session_cleanup() -> None:
    """
    Полная очистка DB в начале тестовой сессии.
    Удаляет ВСЕ транзакционные данные (заказы, инвентарь, рецепты, партии).
    Продукты и расходы без префикса ТЕСТ НЕ трогаются.
    """
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


# ---------------------------------------------------------------------------
# Создание пользователей
# ---------------------------------------------------------------------------

def _create_users() -> Dict[str, User]:
    """
    Создаёт 5 пользователей:
      - admin:    +996700000001  admin123
      - partner:  +996700000002  partner123
      - store_user: +996700000003  store123
      - partner2: +996700000005  partner2pw  (второй партнёр)
      - store_user2: +996700000004  store2pw  (второй магазин)
    """
    admin = User.objects.create(
        phone='+996700000001',
        email='admin@test.local',
        name='Айбек',
        second_name='ТЕСТ-Администратор',
        role='admin',
        is_staff=True,
        is_superuser=True,
    )
    admin.set_password('admin123')
    admin.save()

    partner = User.objects.create(
        phone='+996700000002',
        email='partner@test.local',
        name='Нурлан',
        second_name='ТЕСТ-Партнёр',
        role='partner',
    )
    partner.set_password('partner123')
    partner.save()

    store_user = User.objects.create(
        phone='+996700000003',
        email='store@test.local',
        name='Гүлнара',
        second_name='ТЕСТ-Магазин',
        role='store',
    )
    store_user.set_password('store123')
    store_user.save()

    store_user2 = User.objects.create(
        phone='+996700000004',
        email='store2@test.local',
        name='Бакыт',
        second_name='ТЕСТ-Магазин2',
        role='store',
    )
    store_user2.set_password('store2pw')
    store_user2.save()

    partner2 = User.objects.create(
        phone='+996700000005',
        email='partner2@test.local',
        name='Эрмек',
        second_name='ТЕСТ-Партнёр2',
        role='partner',
    )
    partner2.set_password('partner2pw')
    partner2.save()

    return {
        'admin': admin,
        'partner': partner,
        'store_user': store_user,
        'store_user2': store_user2,
        'partner2': partner2,
    }


# ---------------------------------------------------------------------------
# Создание географии
# ---------------------------------------------------------------------------

def _create_geography() -> Dict[str, Any]:
    """
    Создаёт регионы и города:
      - ТЕСТ Регион → ТЕСТ Город
      - Чуйская область → Бишкек, Токмок
    """
    test_region, _ = Region.objects.get_or_create(name='ТЕСТ Регион')
    test_city, _ = City.objects.get_or_create(region=test_region, name='ТЕСТ Город')

    chuy_region, _ = Region.objects.get_or_create(name='ТЕСТ Чуйская область')
    bishkek, _ = City.objects.get_or_create(region=chuy_region, name='ТЕСТ Бишкек')
    tokmok, _ = City.objects.get_or_create(region=chuy_region, name='ТЕСТ Токмок')

    return {
        'test_region': test_region,
        'test_city': test_city,
        'chuy_region': chuy_region,
        'bishkek': bishkek,
        'tokmok': tokmok,
    }


# ---------------------------------------------------------------------------
# Создание магазинов
# ---------------------------------------------------------------------------

def _create_stores(users: Dict[str, User], geo: Dict[str, Any]) -> Dict[str, Store]:
    """
    Создаёт 2 магазина:
      - store1: активный, утверждённый
      - store2: активный, утверждённый (второй пользователь)
    """
    store1 = Store.objects.create(
        name='ТЕСТ Магазин Айсберг',
        owner=users['store_user'],
        region=geo['test_region'],
        city=geo['test_city'],
        address='ул. Тестовая, 1',
        inn=f"1234567{users['store_user'].id:05d}",
        owner_name='Магазин ТЕСТ',
        phone='+996555111222',
        approval_status='approved',
        is_active=True,
    )

    store2 = Store.objects.create(
        name='ТЕСТ Магазин Арктика',
        owner=users['store_user2'],
        region=geo['chuy_region'],
        city=geo['bishkek'],
        address='пр. Манаса, 55',
        inn=f"1234567{users['store_user2'].id:05d}",
        owner_name='Арктика ТЕСТ',
        phone='+996555333444',
        approval_status='approved',
        is_active=True,
    )

    return {'store1': store1, 'store2': store2}


# ---------------------------------------------------------------------------
# Создание расходов
# ---------------------------------------------------------------------------

def _create_expenses() -> Dict[str, Expense]:
    """
    Создаёт полный набор расходов:
      Физические Сюзерены: мука, фарш, молоко
      Физические Обыватели: лук (→мука), соль (→мука), специи (→фарш)
      Накладные Автоматические: аренда, зарплата, топливо
    """
    # --- Физические Сюзерены ---
    flour = Expense.objects.create(
        name='ТЕСТ Мука пшеничная',
        expense_type=ExpenseType.PHYSICAL,
        expense_status=ExpenseStatus.SUZERAIN,
        expense_state=ExpenseState.MECHANICAL,
        apply_type=ApplyType.REGULAR,
        unit_type=ExpenseUnitType.PER_WEIGHT,
        price_per_unit=Decimal('50.00'),
    )

    minced_meat = Expense.objects.create(
        name='ТЕСТ Фарш говяжий',
        expense_type=ExpenseType.PHYSICAL,
        expense_status=ExpenseStatus.SUZERAIN,
        expense_state=ExpenseState.MECHANICAL,
        apply_type=ApplyType.REGULAR,
        unit_type=ExpenseUnitType.PER_WEIGHT,
        price_per_unit=Decimal('400.00'),
    )

    milk = Expense.objects.create(
        name='ТЕСТ Молоко',
        expense_type=ExpenseType.PHYSICAL,
        expense_status=ExpenseStatus.SUZERAIN,
        expense_state=ExpenseState.MECHANICAL,
        apply_type=ApplyType.REGULAR,
        unit_type=ExpenseUnitType.PER_VOLUME,
        price_per_unit=Decimal('80.00'),
    )

    # --- Физические Обыватели (зависят от Сюзеренов) ---
    onion = Expense.objects.create(
        name='ТЕСТ Лук репчатый',
        expense_type=ExpenseType.PHYSICAL,
        expense_status=ExpenseStatus.CIVILIAN,
        expense_state=ExpenseState.AUTOMATIC,
        apply_type=ApplyType.REGULAR,
        unit_type=ExpenseUnitType.PER_WEIGHT,
        price_per_unit=Decimal('30.00'),
        depends_on_suzerain=flour,
        dependency_ratio=Decimal('0.50'),
    )

    salt = Expense.objects.create(
        name='ТЕСТ Соль',
        expense_type=ExpenseType.PHYSICAL,
        expense_status=ExpenseStatus.CIVILIAN,
        expense_state=ExpenseState.AUTOMATIC,
        apply_type=ApplyType.REGULAR,
        unit_type=ExpenseUnitType.PER_WEIGHT,
        price_per_unit=Decimal('10.00'),
        depends_on_suzerain=flour,
        dependency_ratio=Decimal('0.02'),
    )

    spices = Expense.objects.create(
        name='ТЕСТ Специи',
        expense_type=ExpenseType.PHYSICAL,
        expense_status=ExpenseStatus.CIVILIAN,
        expense_state=ExpenseState.AUTOMATIC,
        apply_type=ApplyType.REGULAR,
        unit_type=ExpenseUnitType.PER_WEIGHT,
        price_per_unit=Decimal('200.00'),
        depends_on_suzerain=minced_meat,
        dependency_ratio=Decimal('0.03'),
    )

    # --- Накладные Автоматические Универсальные ---
    rent = Expense.objects.create(
        name='ТЕСТ Аренда склада',
        expense_type=ExpenseType.OVERHEAD,
        expense_status=ExpenseStatus.VASSAL,
        expense_state=ExpenseState.AUTOMATIC,
        apply_type=ApplyType.UNIVERSAL,
        monthly_amount=Decimal('30000.00'),
        daily_amount=Decimal('1000.00'),
    )

    salary = Expense.objects.create(
        name='ТЕСТ Зарплата персонала',
        expense_type=ExpenseType.OVERHEAD,
        expense_status=ExpenseStatus.VASSAL,
        expense_state=ExpenseState.AUTOMATIC,
        apply_type=ApplyType.UNIVERSAL,
        monthly_amount=Decimal('60000.00'),
        daily_amount=Decimal('2000.00'),
    )

    fuel = Expense.objects.create(
        name='ТЕСТ Топливо',
        expense_type=ExpenseType.OVERHEAD,
        expense_status=ExpenseStatus.VASSAL,
        expense_state=ExpenseState.AUTOMATIC,
        apply_type=ApplyType.UNIVERSAL,
        monthly_amount=Decimal('15000.00'),
        daily_amount=Decimal('500.00'),
    )

    return {
        # Сюзерены
        'flour': flour,
        'minced_meat': minced_meat,
        'milk': milk,
        # Обыватели
        'onion': onion,
        'salt': salt,
        'spices': spices,
        # Накладные
        'rent': rent,
        'salary': salary,
        'fuel': fuel,
    }


# ---------------------------------------------------------------------------
# Создание товаров
# ---------------------------------------------------------------------------

def _create_products() -> Dict[str, Product]:
    """
    Создаёт полный набор товаров:
      - ice_cream: штучный, is_bonus=True (каждый 21-й бесплатно)
      - juice:     штучный, is_bonus=False
      - dumplings: штучный, is_bonus=True (с рецептом)
      - kefir:     штучный, is_bonus=False
      - cheese:    весовой, is_bonus=False
      - beef:      весовой, is_bonus=False
      - butter:    весовой, is_bonus=False
    """
    ice_cream = Product.objects.create(
        name='ТЕСТ Мороженое Пломбир',
        manual_price=Decimal('100.00'),
        markup_percentage=Decimal('30.00'),
        stock_quantity=Decimal('1000'),
        is_available=True,
        is_weight_based=False,
        is_bonus=True,
        popularity_weight=Decimal('2.000000'),
    )

    juice = Product.objects.create(
        name='ТЕСТ Сок Яблочный',
        manual_price=Decimal('50.00'),
        markup_percentage=Decimal('25.00'),
        stock_quantity=Decimal('500'),
        is_available=True,
        is_weight_based=False,
        is_bonus=False,
        popularity_weight=Decimal('1.500000'),
    )

    dumplings = Product.objects.create(
        name='ТЕСТ Пельмени 500г',
        manual_price=Decimal('180.00'),
        markup_percentage=Decimal('35.00'),
        stock_quantity=Decimal('300'),
        is_available=True,
        is_weight_based=False,
        is_bonus=True,
        popularity_weight=Decimal('3.000000'),
    )

    kefir = Product.objects.create(
        name='ТЕСТ Кефир 1л',
        manual_price=Decimal('75.00'),
        markup_percentage=Decimal('20.00'),
        stock_quantity=Decimal('400'),
        is_available=True,
        is_weight_based=False,
        is_bonus=False,
        popularity_weight=Decimal('1.000000'),
    )

    cheese = Product.objects.create(
        name='ТЕСТ Сыр Брынза (весовой)',
        manual_price=Decimal('800.00'),
        markup_percentage=Decimal('40.00'),
        stock_quantity=Decimal('50'),
        is_available=True,
        is_weight_based=True,
        is_bonus=False,
        popularity_weight=Decimal('1.200000'),
    )

    beef = Product.objects.create(
        name='ТЕСТ Мясо Говядина (весовой)',
        manual_price=Decimal('650.00'),
        markup_percentage=Decimal('45.00'),
        stock_quantity=Decimal('100'),
        is_available=True,
        is_weight_based=True,
        is_bonus=False,
        popularity_weight=Decimal('1.800000'),
    )

    butter = Product.objects.create(
        name='ТЕСТ Масло сливочное (весовой)',
        manual_price=Decimal('550.00'),
        markup_percentage=Decimal('30.00'),
        stock_quantity=Decimal('30'),
        is_available=True,
        is_weight_based=True,
        is_bonus=False,
        popularity_weight=Decimal('1.000000'),
    )

    return {
        'ice_cream': ice_cream,
        'juice': juice,
        'dumplings': dumplings,
        'kefir': kefir,
        'cheese': cheese,
        'beef': beef,
        'butter': butter,
    }


# ---------------------------------------------------------------------------
# Создание рецептов товаров
# ---------------------------------------------------------------------------

def _create_recipes(products: Dict[str, Product], expenses: Dict[str, Expense]) -> None:
    """
    Создаёт ProductRecipe для товаров с расходами.

    Пельмени 500г:
      - Мука (суз):  0.200 кг/упак (absolute: 40кг на 200 упак)
      - Фарш (суз):  0.300 кг/упак
      - Лук (обыв):  proportion=0.50 от муки
      - Соль (обыв): proportion=0.02 от муки
      - Специи (обыв): proportion=0.03 от фарша

    Мороженое Пломбир:
      - Молоко (суз): 0.150 л/шт
    """
    dumplings = products['dumplings']

    # Пельмени — Мука (Сюзерен)
    ProductRecipe.objects.create(
        product=dumplings,
        expense=expenses['flour'],
        quantity_per_unit=Decimal('0.2000'),
        absolute_quantity=Decimal('40.000'),
        product_quantity=Decimal('200'),
    )

    # Пельмени — Фарш (Сюзерен)
    ProductRecipe.objects.create(
        product=dumplings,
        expense=expenses['minced_meat'],
        quantity_per_unit=Decimal('0.3000'),
        absolute_quantity=Decimal('60.000'),
        product_quantity=Decimal('200'),
    )

    # Пельмени — Лук (Обыватель, пропорция)
    ProductRecipe.objects.create(
        product=dumplings,
        expense=expenses['onion'],
        proportion=Decimal('0.50'),
    )

    # Пельмени — Соль (Обыватель, пропорция)
    ProductRecipe.objects.create(
        product=dumplings,
        expense=expenses['salt'],
        proportion=Decimal('0.02'),
    )

    # Мороженое — Молоко (Сюзерен)
    ProductRecipe.objects.create(
        product=products['ice_cream'],
        expense=expenses['milk'],
        quantity_per_unit=Decimal('0.1500'),
        absolute_quantity=Decimal('15.000'),
        product_quantity=Decimal('100'),
    )


# ---------------------------------------------------------------------------
# Создание инвентаря партнёра
# ---------------------------------------------------------------------------

def _create_partner_inventory(partner: User, products: Dict[str, Product]) -> None:
    """
    Заполняет склад партнёра для всех товаров.
    Весовые — 50 кг/л, штучные — 100 шт.
    """
    quantities = {
        'ice_cream':  Decimal('100'),
        'juice':      Decimal('100'),
        'dumplings':  Decimal('100'),
        'kefir':      Decimal('100'),
        'cheese':     Decimal('50'),
        'beef':       Decimal('100'),
        'butter':     Decimal('30'),
    }
    for key, product in products.items():
        PartnerInventory.objects.create(
            partner=partner,
            product=product,
            quantity=quantities[key],
            reserved_quantity=Decimal('0'),
        )


# ---------------------------------------------------------------------------
# Создание полного цикла заказа
# ---------------------------------------------------------------------------

def _create_preorder(data: Dict[str, Any]) -> StoreOrder:
    """
    Создаёт preorder и проводит его через полный цикл:
    PENDING → IN_TRANSIT → ACCEPTED

    Состав заказа:
      - 10 шт Мороженого (бонусный товар)
      - 5  шт Сока
      - 2.5 кг Сыра (весовой)
    """
    partner = data['partner']
    store_user = data['store_user']
    store = data['store1']
    products = data['products']

    order = StoreOrder.objects.create(
        order_type='preorder',
        store=store,
        created_by=store_user,
        status=StoreOrderStatus.PENDING,
    )

    items_data = [
        ('ice_cream', Decimal('10'), None),
        ('juice',     Decimal('5'),  None),
        ('cheese',    Decimal('2.5'), Decimal('2.500')),  # весовой
    ]

    for product_key, quantity, weight in items_data:
        product = products[product_key]
        item = StoreOrderItem(
            order=order,
            product=product,
            quantity=quantity,
            price=product.final_price,
        )
        if weight is not None:
            item.weight = weight
        item.save()

    order.calculate_total()
    order.save()

    # Шаг 2: Admin утверждает (через partner — для тестов)
    OrderWorkflowService.admin_approve_order(order=order, admin_user=partner)

    # Шаг 3: Partner подтверждает доставку через реальный API endpoint
    client = APIClient()
    client.force_authenticate(user=partner)
    response = client.post(
        f'/api/stores/stores/{store.id}/basket/confirm/',
        {'prepayment_amount': '1000'},
        format='json',
    )
    assert response.status_code == 200, (
        f"confirm_basket failed: {getattr(response, 'data', response.content)}"
    )

    order.refresh_from_db()
    store.refresh_from_db()
    return order


# ---------------------------------------------------------------------------
# Hooks сессии
# ---------------------------------------------------------------------------

def pytest_sessionstart(session):
    """Очистка транзакционных данных в самом начале тестовой сессии."""
    _full_session_cleanup()


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
    """
    Полные базовые данные для тестов:
    - 5 пользователей (admin, partner, store_user, store_user2, partner2)
    - 2 магазина (store1, store2)
    - 2 региона с городами
    - 9 расходов (3 суз + 3 обыв + 3 накладных)
    - 7 товаров (4 штучных + 3 весовых)
    - Рецепты для Пельменей и Мороженого
    - Инвентарь партнёра (всех 7 товаров)
    """
    users = _create_users()
    geo = _create_geography()
    stores = _create_stores(users, geo)
    expenses = _create_expenses()
    products = _create_products()
    _create_recipes(products, expenses)
    _create_partner_inventory(users['partner'], products)

    return {
        **users,
        **stores,
        **geo,
        'expenses': expenses,
        'products': products,
    }


@pytest.fixture(autouse=True)
def ensure_base_data(base_data):
    """Автоматически создаёт базовые данные для всех тестов."""
    return


# ---------------------------------------------------------------------------
# Удобные алиасы для часто используемых объектов
# ---------------------------------------------------------------------------

@pytest.fixture()
def admin(base_data):
    return base_data['admin']


@pytest.fixture()
def partner(base_data):
    return base_data['partner']


@pytest.fixture()
def partner2(base_data):
    return base_data['partner2']


@pytest.fixture()
def store_user(base_data):
    return base_data['store_user']


@pytest.fixture()
def store_user2(base_data):
    return base_data['store_user2']


@pytest.fixture()
def store(base_data):
    return base_data['store1']


@pytest.fixture()
def store1(base_data):
    return base_data['store1']


@pytest.fixture()
def store2(base_data):
    return base_data['store2']


@pytest.fixture()
def products(base_data):
    return base_data['products']


@pytest.fixture()
def expenses(base_data):
    return base_data['expenses']


# --- Товары ---

@pytest.fixture()
def ice_cream(products):
    return products['ice_cream']


@pytest.fixture()
def juice(products):
    return products['juice']


@pytest.fixture()
def dumplings(products):
    return products['dumplings']


@pytest.fixture()
def kefir(products):
    return products['kefir']


@pytest.fixture()
def cheese(products):
    return products['cheese']


@pytest.fixture()
def beef(products):
    return products['beef']


@pytest.fixture()
def butter(products):
    return products['butter']


@pytest.fixture()
def meat(products):
    """Алиас для beef (обратная совместимость)."""
    return products['beef']


# --- Расходы ---

@pytest.fixture()
def flour(expenses):
    """Мука — физический Сюзерен."""
    return expenses['flour']


@pytest.fixture()
def minced_meat(expenses):
    """Фарш — физический Сюзерен."""
    return expenses['minced_meat']


@pytest.fixture()
def milk(expenses):
    """Молоко — физический Сюзерен."""
    return expenses['milk']


@pytest.fixture()
def onion(expenses):
    """Лук — физический Обыватель (→Мука)."""
    return expenses['onion']


@pytest.fixture()
def rent(expenses):
    """Аренда — накладной Вассал."""
    return expenses['rent']


@pytest.fixture()
def salary(expenses):
    """Зарплата — накладной Вассал."""
    return expenses['salary']


# --- Заказы ---

@pytest.fixture()
def preorder(base_data) -> StoreOrder:
    """
    Готовый заказ: PENDING → IN_TRANSIT → ACCEPTED.
    Состав: 10 мороженых + 5 соков + 2.5кг сыра.
    Предоплата: 1000 сом.
    """
    return _create_preorder(base_data)


@pytest.fixture()
def pending_order(base_data) -> StoreOrder:
    """
    Заказ в статусе PENDING (ещё не утверждён).
    Состав: 5 Пельменей + 3 Кефира.
    """
    store = base_data['store1']
    store_user = base_data['store_user']
    products = base_data['products']

    order = StoreOrder.objects.create(
        order_type='preorder',
        store=store,
        created_by=store_user,
        status=StoreOrderStatus.PENDING,
    )
    StoreOrderItem.objects.create(
        order=order,
        product=products['dumplings'],
        quantity=Decimal('5'),
        price=products['dumplings'].final_price,
    )
    StoreOrderItem.objects.create(
        order=order,
        product=products['kefir'],
        quantity=Decimal('3'),
        price=products['kefir'].final_price,
    )
    order.calculate_total()
    order.save()
    return order


@pytest.fixture()
def paid_order(base_data) -> StoreOrder:
    """
    Заказ ACCEPTED с полностью оплаченным долгом.
    Полезен для тестов отчётов и статистики.
    """
    order = _create_preorder(base_data)

    # Добавляем полную оплату остатка
    outstanding = order.debt_amount - order.paid_amount
    if outstanding > 0:
        DebtPayment.objects.create(
            order=order,
            store=order.store,
            amount=outstanding,
            comment='Полная оплата ТЕСТ',
            paid_by=base_data['store_user'],
            received_by=base_data['partner'],
        )
        order.paid_amount += outstanding
        order.save()

    order.refresh_from_db()
    return order
