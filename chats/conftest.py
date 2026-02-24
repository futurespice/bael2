"""
chats/conftest.py

Фикстуры для тестов чатов.

ВАЖНО о среде выполнения:
  - pytest-django НЕ установлен; Django инициализирован вручную в корневом conftest.py
  - Фикстуры clean_state, ensure_base_data (autouse) из корневого conftest работают для всех тестов
  - Корневые фикстуры: admin, partner, store_user (без суффикса) — используем их напрямую
  - clean_state НЕ очищает Chat/Message — за это отвечает clean_chats ниже
  - WebSocket тесты требуют InMemoryChannelLayer вместо RedisChannelLayer
  - Async тесты: @pytest.mark.anyio (anyio==4.11.0 установлен)
"""

import pytest
from django.test import override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from chats.models import Chat, Message
from users.models import User

# ---------------------------------------------------------------------------
# Настройки channels для тестов — заменяем Redis на InMemory
# ---------------------------------------------------------------------------

TEST_CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}


# ---------------------------------------------------------------------------
# Вспомогательные функции (переиспользуются в tests.py)
# ---------------------------------------------------------------------------

def get_jwt_token(user) -> str:
    """Возвращает JWT access-токен для пользователя."""
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


def make_chat(user1, user2) -> Chat:
    """Создаёт чат между двумя пользователями."""
    chat = Chat.objects.create()
    chat.participants.add(user1, user2)
    return chat


def make_message(chat: Chat, sender, content: str = "Тест") -> Message:
    """Создаёт сообщение в чате."""
    return Message.objects.create(chat=chat, sender=sender, content=content)


# ---------------------------------------------------------------------------
# Автоматическая очистка Chat/Message между тестами
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_chats():
    """Очищает Chat и Message до и после каждого теста чатов."""
    Message.objects.all().delete()
    Chat.objects.all().delete()
    yield
    Message.objects.all().delete()
    Chat.objects.all().delete()


# ---------------------------------------------------------------------------
# Дополнительный пользователь магазина
# store_user из корневого conftest уже создаётся через ensure_base_data;
# +996700... — маска, которую clean_state использует для очистки
# ---------------------------------------------------------------------------

@pytest.fixture()
def store_user_2():
    """Второй пользователь с ролью store для тестов изоляции."""
    user, _ = User.objects.get_or_create(
        phone='+996700000099',
        defaults=dict(
            email='store2@test.local',
            name='Магазин2',
            second_name='ТЕСТ',
            role='store',
            is_active=True,
        ),
    )
    user.set_password('store123')
    user.save()
    return user


# ---------------------------------------------------------------------------
# Готовые чаты (используют admin/partner/store_user из корневого conftest)
# ---------------------------------------------------------------------------

@pytest.fixture()
def chat_partner_store(partner, store_user):
    """Чат между партнёром и магазином."""
    return make_chat(partner, store_user)


@pytest.fixture()
def chat_admin_store(admin, store_user):
    """Чат между админом и магазином."""
    return make_chat(admin, store_user)


# ---------------------------------------------------------------------------
# Override CHANNEL_LAYERS для WebSocket тестов
# ---------------------------------------------------------------------------

@pytest.fixture()
def in_memory_channel_layers():
    """
    Заменяет RedisChannelLayer → InMemoryChannelLayer на время теста.
    Используется в WS-тестах через параметр фикстуры или autouse.
    """
    with override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS):
        yield


@pytest.fixture()
def ws_app(in_memory_channel_layers):
    """
    Возвращает ASGI-приложение с InMemoryChannelLayer.
    Использовать в WS-тестах вместо прямого импорта config.asgi.application.
    """
    from config.asgi import application
    return application
