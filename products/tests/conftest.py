"""
Локальный conftest для products/tests/.

ЗАЧЕМ:
  Глобальный conftest.py имеет autouse=True фикстуры (clean_state, ensure_base_data),
  которые создают полный стек данных (users, stores, partner_inventory).
  Для unit-тестов products это лишний overhead и потенциальный источник конфликтов.

  Этот файл переопределяет эти autouse-фикстуры для директории products/tests/,
  заменяя их на no-op, чтобы тесты были изолированными и быстрыми.

  Pytest ищет conftest.py от корня до директории теста — local conftest
  имеет приоритет над глобальным для своей директории.
"""

import pytest


# =============================================================================
# OVERRIDE GLOBAL AUTOUSE FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def clean_state(db):
    """
    Локальный override: не делаем ручную очистку таблиц.
    Изоляция обеспечивается через pytest-django transaction rollback (db fixture).
    """
    yield


@pytest.fixture(autouse=True)
def ensure_base_data():
    """
    Локальный override: не создаём глобальные тестовые данные
    (users, stores, products из conftest корня).
    Каждый тест products создаёт только то, что ему нужно.
    """
    yield
