"""
chats/tests.py

Тесты для приложения чатов.

Инфраструктура:
  - Django инициализирован вручную в корневом conftest.py (без pytest-django)
  - Фикстуры admin, partner, store_user, clean_state — из корневого conftest
  - clean_chats, store_user_2, chat_partner_store, ws_app — из chats/conftest.py
  - Async-тесты: @pytest.mark.anyio (anyio 4.11.0)
  - WS-тесты используют ws_app (InMemoryChannelLayer) вместо Redis

Запуск всех тестов:
  pytest chats/tests.py -v

Только REST (без async):
  pytest chats/tests.py -v -k "not anyio"

Только WebSocket:
  pytest chats/tests.py -v -k "anyio" или -k "ws_"

Включая xfail (задокументированные пробелы):
  pytest chats/tests.py -v --runxfail
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from chats.models import Chat, Message
from chats.conftest import get_jwt_token, make_chat, make_message


# ---------------------------------------------------------------------------
# Вспомогательная функция
# ---------------------------------------------------------------------------

def auth_client(user) -> APIClient:
    """APIClient с JWT Bearer авторизацией."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {get_jwt_token(user)}")
    return client


# ===========================================================================
# GET /api/chats/
# ===========================================================================

class TestChatList:

    def test_returns_grouped_by_role(self, partner, store_user, admin):
        """Ответ сгруппирован по ролям: admins, partners, stores."""
        response = auth_client(partner).get("/api/chats/")

        assert response.status_code == status.HTTP_200_OK
        assert "admins" in response.data
        assert "partners" in response.data
        assert "stores" in response.data

    def test_store_sees_only_admins_and_partners(self, store_user, partner, admin):
        """Магазин видит только категории admins и partners."""
        response = auth_client(store_user).get("/api/chats/")

        assert response.status_code == status.HTTP_200_OK
        assert "admins" in response.data
        assert "partners" in response.data
        assert "stores" not in response.data

    def test_chats_auto_created_on_first_call(self, partner, store_user, admin):
        """При первом вызове чаты создаются автоматически для всех доступных пользователей."""
        response = auth_client(partner).get("/api/chats/")

        assert response.status_code == status.HTTP_200_OK
        # У partner есть чаты с admin (admins) и store_user (stores)
        assert len(response.data["admins"]) >= 1
        assert len(response.data["stores"]) >= 1

    def test_response_contains_last_message_and_unread_count(self, partner, store_user, admin):
        """Каждый чат содержит last_message и unread_count."""
        # Вызываем сначала чтобы чат создался
        auth_client(partner).get("/api/chats/")
        chat = Chat.objects.filter(participants=partner).filter(participants=store_user).first()
        make_message(chat, store_user, "Новое сообщение")

        response = auth_client(partner).get("/api/chats/")

        stores_chats = response.data["stores"]
        chat_data = next(c for c in stores_chats if c["id"] == chat.id)
        assert chat_data["last_message"]["content"] == "Новое сообщение"
        assert chat_data["unread_count"] == 1

    def test_unauthenticated_request_returns_401(self):
        """Без авторизации — 401."""
        assert APIClient().get("/api/chats/").status_code == status.HTTP_401_UNAUTHORIZED


# ===========================================================================
# POST /api/chats/
# ===========================================================================

class TestChatCreate:

    def test_partner_creates_chat_with_store(self, partner, store_user):
        """Партнёр успешно создаёт чат с магазином."""
        response = auth_client(partner).post("/api/chats/", {"user_id": store_user.id})

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] is not None
        assert Chat.objects.count() == 1

    def test_duplicate_request_returns_existing_chat(self, partner, store_user):
        """Повторный POST возвращает существующий чат без дублирования."""
        existing = make_chat(partner, store_user)

        response = auth_client(partner).post("/api/chats/", {"user_id": store_user.id})

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == existing.id
        assert Chat.objects.count() == 1  # дубля нет

    def test_store_to_store_chat_is_forbidden(self, store_user, store_user_2):
        """Магазин → Магазин запрещено."""
        response = auth_client(store_user).post("/api/chats/", {"user_id": store_user_2.id})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Chat.objects.count() == 0

    def test_chat_with_self_is_forbidden(self, partner):
        """Нельзя создать чат с самим собой."""
        response = auth_client(partner).post("/api/chats/", {"user_id": partner.id})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_user_returns_400(self, partner):
        """Несуществующий пользователь — 400."""
        response = auth_client(partner).post("/api/chats/", {"user_id": 999999})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_store_can_chat_with_admin(self, store_user, admin):
        """Магазин → Админ разрешено."""
        response = auth_client(store_user).post("/api/chats/", {"user_id": admin.id})

        assert response.status_code == status.HTTP_200_OK

    def test_admin_can_chat_with_partner(self, admin, partner):
        """Админ → Партнёр разрешено."""
        response = auth_client(admin).post("/api/chats/", {"user_id": partner.id})

        assert response.status_code == status.HTTP_200_OK


# ===========================================================================
# GET /api/chats/{id}/messages/ и POST /api/chats/{id}/messages/
# ===========================================================================

class TestChatMessages:

    def test_get_returns_full_history(self, partner, store_user, chat_partner_store):
        """GET возвращает историю сообщений в хронологическом порядке."""
        make_message(chat_partner_store, partner, "Первое")
        make_message(chat_partner_store, store_user, "Второе")

        response = auth_client(partner).get(f"/api/chats/{chat_partner_store.id}/messages/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        assert response.data[0]["content"] == "Первое"

    def test_get_marks_interlocutor_messages_read(self, partner, store_user, chat_partner_store):
        """GET автоматически помечает чужие сообщения прочитанными."""
        msg = make_message(chat_partner_store, store_user, "Непрочитано")
        assert msg.is_read is False

        auth_client(partner).get(f"/api/chats/{chat_partner_store.id}/messages/")

        msg.refresh_from_db()
        assert msg.is_read is True

    def test_get_does_not_mark_own_messages_read(self, partner, store_user, chat_partner_store):
        """GET не трогает is_read у собственных сообщений."""
        msg = make_message(chat_partner_store, partner, "Моё")

        auth_client(partner).get(f"/api/chats/{chat_partner_store.id}/messages/")

        msg.refresh_from_db()
        assert msg.is_read is False

    def test_get_by_non_participant_returns_404(self, store_user_2, chat_partner_store):
        """Чужой пользователь получает 404."""
        response = auth_client(store_user_2).get(f"/api/chats/{chat_partner_store.id}/messages/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_post_creates_message(self, partner, store_user, chat_partner_store):
        """POST создаёт сообщение в БД и возвращает его."""
        response = auth_client(partner).post(
            f"/api/chats/{chat_partner_store.id}/messages/",
            {"content": "Привет!"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Message.objects.count() == 1
        assert response.data["content"] == "Привет!"

    def test_post_sets_correct_sender(self, partner, store_user, chat_partner_store):
        """Sender в ответе совпадает с авторизованным пользователем."""
        response = auth_client(partner).post(
            f"/api/chats/{chat_partner_store.id}/messages/",
            {"content": "Проверка sender"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["sender"]["id"] == partner.id

    def test_post_by_non_participant_returns_404(self, store_user_2, chat_partner_store):
        """Чужой пользователь не может отправить сообщение."""
        response = auth_client(store_user_2).post(
            f"/api/chats/{chat_partner_store.id}/messages/",
            {"content": "Взлом"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Message.objects.count() == 0

    def test_post_updates_chat_timestamp(self, partner, store_user, chat_partner_store):
        """Отправка сообщения обновляет updated_at чата."""
        old_ts = chat_partner_store.updated_at

        auth_client(partner).post(
            f"/api/chats/{chat_partner_store.id}/messages/",
            {"content": "Обновляем"},
        )
        chat_partner_store.refresh_from_db()

        assert chat_partner_store.updated_at > old_ts

    def test_post_without_content_returns_400(self, partner, chat_partner_store):
        """Запрос без поля content — 400."""
        response = auth_client(partner).post(
            f"/api/chats/{chat_partner_store.id}/messages/",
            {},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_nonexistent_chat_returns_404(self, partner):
        """Запрос к несуществующему чату — 404."""
        response = auth_client(partner).get("/api/chats/999999/messages/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# POST /api/chats/{id}/read/
# ===========================================================================

class TestMarkRead:

    def test_marks_interlocutor_messages_read(self, partner, store_user, chat_partner_store):
        """Помечает сообщения собеседника прочитанными, возвращает счётчик."""
        make_message(chat_partner_store, store_user, "Раз")
        make_message(chat_partner_store, store_user, "Два")

        response = auth_client(partner).post(f"/api/chats/{chat_partner_store.id}/read/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["marked_read"] == 2
        assert Message.objects.filter(is_read=False).count() == 0

    def test_does_not_mark_own_messages(self, partner, store_user, chat_partner_store):
        """Собственные сообщения не помечаются."""
        make_message(chat_partner_store, partner, "Моё")

        response = auth_client(partner).post(f"/api/chats/{chat_partner_store.id}/read/")

        assert response.data["marked_read"] == 0

    def test_returns_0_if_all_already_read(self, partner, store_user, chat_partner_store):
        """Если всё прочитано — возвращает 0."""
        msg = make_message(chat_partner_store, store_user, "Уже прочитано")
        msg.is_read = True
        msg.save()

        response = auth_client(partner).post(f"/api/chats/{chat_partner_store.id}/read/")

        assert response.data["marked_read"] == 0

    def test_non_participant_gets_404(self, store_user_2, chat_partner_store):
        """Не-участник получает 404."""
        response = auth_client(store_user_2).post(f"/api/chats/{chat_partner_store.id}/read/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# GET /api/chats/users/
# ===========================================================================

class TestAvailableUsers:

    def test_store_sees_only_partner_and_admin(self, store_user, partner, admin, store_user_2):
        """Магазин не видит других магазинов в списке."""
        response = auth_client(store_user).get("/api/chats/users/")

        assert response.status_code == status.HTTP_200_OK
        roles = {u["role"] for u in response.data}
        assert "store" not in roles

    def test_partner_sees_all_except_self(self, partner, admin, store_user):
        """Партнёр видит всех кроме себя."""
        response = auth_client(partner).get("/api/chats/users/")

        ids = [u["id"] for u in response.data]
        assert partner.id not in ids
        assert admin.id in ids
        assert store_user.id in ids

    def test_inactive_user_is_hidden(self, partner, store_user):
        """Неактивный пользователь не виден."""
        store_user.is_active = False
        store_user.save()

        try:
            response = auth_client(partner).get("/api/chats/users/")
            assert store_user.id not in [u["id"] for u in response.data]
        finally:
            # Восстанавливаем для следующих тестов
            store_user.is_active = True
            store_user.save()

    def test_user_has_chat_id_if_chat_exists(self, partner, store_user):
        """chat_id не None, если чат с этим пользователем уже существует."""
        chat = make_chat(partner, store_user)

        response = auth_client(partner).get("/api/chats/users/")

        user_data = next(u for u in response.data if u["id"] == store_user.id)
        assert user_data["chat_id"] == chat.id

    def test_chat_auto_created_if_not_exists(self, partner, store_user):
        """GET /users/ авто-создаёт чат если его ещё нет, chat_id всегда не None."""
        response = auth_client(partner).get("/api/chats/users/")

        user_data = next(u for u in response.data if u["id"] == store_user.id)
        assert user_data["chat_id"] is not None
        assert Chat.objects.filter(participants=partner).filter(participants=store_user).exists()


# ===========================================================================
# Матрица ролей (все комбинации из ТЗ)
# ===========================================================================

class TestRoleMatrix:
    """Проверяет все разрешённые и запрещённые пары ролей."""

    def test_store_to_partner(self, store_user, partner):
        assert auth_client(store_user).post(
            "/api/chats/", {"user_id": partner.id}
        ).status_code == status.HTTP_200_OK

    def test_store_to_admin(self, store_user, admin):
        assert auth_client(store_user).post(
            "/api/chats/", {"user_id": admin.id}
        ).status_code == status.HTTP_200_OK

    def test_store_to_store_blocked(self, store_user, store_user_2):
        assert auth_client(store_user).post(
            "/api/chats/", {"user_id": store_user_2.id}
        ).status_code == status.HTTP_400_BAD_REQUEST

    def test_partner_to_admin(self, partner, admin):
        assert auth_client(partner).post(
            "/api/chats/", {"user_id": admin.id}
        ).status_code == status.HTTP_200_OK

    def test_admin_to_store(self, admin, store_user):
        assert auth_client(admin).post(
            "/api/chats/", {"user_id": store_user.id}
        ).status_code == status.HTTP_200_OK

    def test_admin_to_partner(self, admin, partner):
        assert auth_client(admin).post(
            "/api/chats/", {"user_id": partner.id}
        ).status_code == status.HTTP_200_OK


# ===========================================================================
# Граничные случаи
# ===========================================================================

class TestEdgeCases:

    def test_unicode_emoji_and_special_chars(self, partner, store_user, chat_partner_store):
        """Кириллица, emoji, HTML-символы сохраняются без изменений."""
        content = 'Привет! 😊 <script>xss</script> & "кавычки"'
        response = auth_client(partner).post(
            f"/api/chats/{chat_partner_store.id}/messages/",
            {"content": content},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["content"] == content

    def test_very_long_message_saved(self, partner, store_user, chat_partner_store):
        """TextField без лимита принимает длинные сообщения."""
        content = "Тест " * 1000
        response = auth_client(partner).post(
            f"/api/chats/{chat_partner_store.id}/messages/",
            {"content": content},
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_unread_count_only_counts_interlocutor_messages(
        self, partner, store_user, chat_partner_store
    ):
        """unread_count считает только непрочитанные сообщения собеседника, не свои."""
        make_message(chat_partner_store, store_user, "От магазина")  # +1 unread для partner
        make_message(chat_partner_store, partner, "От партнёра")     # НЕ считается

        response = auth_client(partner).get("/api/chats/")

        assert response.data[0]["unread_count"] == 1


# ===========================================================================
# WebSocket тесты (anyio + InMemoryChannelLayer)
# ===========================================================================

@pytest.mark.anyio
async def test_ws_valid_token_connects(partner, store_user, chat_partner_store, ws_app):
    """Участник с валидным токеном успешно подключается."""
    from channels.testing import WebsocketCommunicator

    comm = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(partner)}",
    )
    connected, _ = await comm.connect()

    assert connected
    await comm.disconnect()


@pytest.mark.anyio
async def test_ws_no_token_rejected_4001(store_user, chat_partner_store, ws_app):
    """Подключение без токена закрывается с кодом 4001."""
    from channels.testing import WebsocketCommunicator

    comm = WebsocketCommunicator(ws_app, f"/ws/chats/{chat_partner_store.id}/")
    connected, code = await comm.connect()

    assert not connected
    assert code == 4001


@pytest.mark.anyio
async def test_ws_non_participant_rejected_4003(store_user_2, chat_partner_store, ws_app):
    """Не-участник отклоняется с кодом 4003."""
    from channels.testing import WebsocketCommunicator

    comm = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(store_user_2)}",
    )
    connected, code = await comm.connect()

    assert not connected
    assert code == 4003


@pytest.mark.anyio
async def test_ws_message_echoed_back(partner, store_user, chat_partner_store, ws_app):
    """Отправитель получает своё сообщение обратно с корректными полями."""
    from channels.testing import WebsocketCommunicator

    comm = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(partner)}",
    )
    await comm.connect()

    await comm.send_json_to({"content": "Привет через WS!"})
    response = await comm.receive_json_from(timeout=5)

    assert response["content"] == "Привет через WS!"
    assert response["sender_id"] == partner.id
    assert response["chat_id"] == chat_partner_store.id
    assert "id" in response
    assert "created_at" in response
    assert response["is_read"] is False

    await comm.disconnect()


@pytest.mark.anyio
async def test_ws_message_delivered_to_all_participants(
    partner, store_user, chat_partner_store, ws_app
):
    """Сообщение доставляется обоим подключённым участникам."""
    from channels.testing import WebsocketCommunicator

    comm_p = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(partner)}",
    )
    comm_s = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(store_user)}",
    )

    await comm_p.connect()
    await comm_s.connect()

    await comm_p.send_json_to({"content": "Всем привет!"})

    msg_p = await comm_p.receive_json_from(timeout=5)
    msg_s = await comm_s.receive_json_from(timeout=5)

    assert msg_p["content"] == "Всем привет!"
    assert msg_s["content"] == "Всем привет!"

    await comm_p.disconnect()
    await comm_s.disconnect()


@pytest.mark.anyio
async def test_ws_message_persisted_in_db(partner, store_user, chat_partner_store, ws_app):
    """WS-сообщение сохраняется в базе данных."""
    from asgiref.sync import sync_to_async
    from channels.testing import WebsocketCommunicator

    comm = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(partner)}",
    )
    await comm.connect()

    await comm.send_json_to({"content": "Сохраняем в БД"})
    await comm.receive_json_from(timeout=5)

    count = await sync_to_async(Message.objects.count)()
    assert count == 1

    await comm.disconnect()


@pytest.mark.anyio
async def test_ws_whitespace_only_returns_error(partner, store_user, chat_partner_store, ws_app):
    """Сообщение из пробелов → ошибка, в БД не сохраняется."""
    from asgiref.sync import sync_to_async
    from channels.testing import WebsocketCommunicator

    comm = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(partner)}",
    )
    await comm.connect()

    await comm.send_json_to({"content": "     "})
    response = await comm.receive_json_from(timeout=5)

    assert "error" in response
    count = await sync_to_async(Message.objects.count)()
    assert count == 0

    await comm.disconnect()


@pytest.mark.anyio
async def test_ws_invalid_json_returns_error(partner, store_user, chat_partner_store, ws_app):
    """Некорректный JSON → ошибка."""
    from channels.testing import WebsocketCommunicator

    comm = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(partner)}",
    )
    await comm.connect()

    await comm.send_to(text_data="{это не JSON{{")
    response = await comm.receive_json_from(timeout=5)

    assert "error" in response
    await comm.disconnect()


@pytest.mark.anyio
async def test_ws_chat_isolation(partner, store_user, store_user_2, chat_partner_store, ws_app):
    """Сообщение не «протекает» в другой чат."""
    from asgiref.sync import sync_to_async
    from channels.testing import WebsocketCommunicator

    chat_other = await sync_to_async(make_chat)(partner, store_user_2)

    comm_1 = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_partner_store.id}/?token={get_jwt_token(partner)}",
    )
    comm_2 = WebsocketCommunicator(
        ws_app,
        f"/ws/chats/{chat_other.id}/?token={get_jwt_token(store_user_2)}",
    )

    await comm_1.connect()
    await comm_2.connect()

    await comm_1.send_json_to({"content": "Только для чата 1"})
    await comm_1.receive_json_from(timeout=5)  # сам получает

    no_msg = await comm_2.receive_nothing(timeout=1)
    assert no_msg is True  # во второй чат ничего не пришло

    await comm_1.disconnect()
    await comm_2.disconnect()


# ===========================================================================
# Задокументированные пробелы в реализации (xfail)
# ===========================================================================

class TestKnownGaps:
    """
    Функционал из ТЗ, который отсутствует в коде.
    xfail = провалится, пока не будет реализован.
    При реализации — станет xpass.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "MISSING: Message.message_type и Message.file_url. "
            "ТЗ §18.1: поддержка типов image/video/document/audio. "
            "Нужна миграция и обновление serializer/consumer."
        ),
    )
    def test_send_image_type_message(self, partner, store_user, chat_partner_store):
        response = auth_client(partner).post(
            f"/api/chats/{chat_partner_store.id}/messages/",
            {"message_type": "image", "file_url": "https://cdn.example.com/img.jpg"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["message_type"] == "image"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "MISSING: DELETE /api/messages/{id}/. "
            "ТЗ §18.1: удаление у всех / только у себя. "
            "Нет эндпоинта в urls.py и поля deleted_by_users в модели."
        ),
    )
    def test_delete_message_for_all(self, partner, store_user, chat_partner_store):
        msg = make_message(chat_partner_store, partner)
        response = auth_client(partner).delete(f"/api/messages/{msg.id}/")
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "MISSING: Пагинация в ChatMessagesView. "
            "GET /api/chats/{id}/messages/ возвращает все сообщения без ограничений. "
            "При 10 000+ сообщений — проблема производительности."
        ),
    )
    def test_messages_paginated(self, partner, store_user, chat_partner_store):
        for i in range(150):
            make_message(chat_partner_store, partner, f"Msg {i}")

        response = auth_client(partner).get(
            f"/api/chats/{chat_partner_store.id}/messages/"
        )
        assert len(response.data) <= 50  # не более страницы
