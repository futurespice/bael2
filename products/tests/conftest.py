"""
Локальный conftest для products/tests/.

ЗАЧЕМ:
  Глобальный conftest.py имеет autouse=True фикстуры (clean_state, ensure_base_data),
  которые создают полный стек данных (users, stores, partner_inventory).
  Для unit-тестов products это лишний overhead и потенциальный источник конфликтов.

  Этот файл переопределяет autouse-фикстуры для директории products/tests/,
  обеспечивая ПОЛНУЮ изоляцию: перед каждым тестом удаляются ВСЕ продукты и расходы
  (не только ТЕСТ-префиксованные), так как тесты здесь создают свои собственные данные.
"""

import pytest

from products.models import Product, Expense, ProductRecipe, ProductionBatch


# =============================================================================
# OVERRIDE GLOBAL AUTOUSE FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def clean_state():
    """
    Локальный override: полная очистка Products/Expenses перед каждым тестом.

    Удаляем ВСЕ продукты и расходы (включая нетестовые данные в db.sqlite3),
    чтобы тесты видели ровно то, что создаёт их setUp() — и ничего лишнего.
    Восстановление после теста гарантируется через Django TestCase rollback
    + повторная очистка в teardown этой фикстуры.
    """
    # Очистка до теста
    ProductRecipe.objects.all().delete()
    ProductionBatch.objects.all().delete()
    Product.objects.all().delete()
    Expense.objects.all().delete()
    yield
    # Очистка после теста (на случай если Django TestCase не откатил)
    ProductRecipe.objects.all().delete()
    ProductionBatch.objects.all().delete()
    Product.objects.all().delete()
    Expense.objects.all().delete()


@pytest.fixture(autouse=True)
def ensure_base_data():
    """
    Локальный override: не создаём глобальные тестовые данные
    (users, stores, products из conftest корня).
    Каждый тест products создаёт только то, что ему нужно.
    """
    yield
