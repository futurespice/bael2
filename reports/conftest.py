"""
Локальный conftest для reports/.

Переопределяет глобальные autouse-фикстуры.
Тесты reports создают свои данные в setUp() и изолированы через Django TestCase.
"""
import pytest

from orders.models import (
    StoreOrder, StoreOrderItem, DebtPayment,
    DefectiveProduct, ReturnedItem,
)
from products.models import Product, Expense, ProductRecipe, ProductionBatch, PartnerExpense
from stores.models import Store, Region, City, StoreInventory, PartnerInventory
from users.models import User


@pytest.fixture(autouse=True)
def clean_state():
    """Полная очистка перед каждым тестом в reports/."""
    _wipe()
    yield
    _wipe()


@pytest.fixture(autouse=True)
def ensure_base_data():
    """Не создаём глобальные тестовые данные — тесты делают свои."""
    yield


def _wipe():
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
    Product.objects.all().delete()
    Expense.objects.all().delete()
    Store.objects.all().delete()
    City.objects.all().delete()
    Region.objects.all().delete()
    User.objects.filter(phone__startswith='+996700').delete()
