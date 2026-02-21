import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)
User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer для чатов.

    Подключение: ws://.../ws/chats/<chat_id>/?token=<jwt_token>

    Входящее сообщение (JSON):
      { "content": "текст сообщения" }

    Исходящее сообщение (JSON):
      {
        "id": 1,
        "chat_id": 5,
        "sender_id": 3,
        "sender_name": "Иван Иванов",
        "content": "текст",
        "is_read": false,
        "created_at": "2024-01-01T12:00:00Z"
      }
    """

    async def connect(self):
        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        self.room_group_name = f'chat_{self.chat_id}'
        self.user = self.scope.get('user')

        if not self.user or isinstance(self.user, AnonymousUser) or not self.user.is_active:
            await self.close(code=4001)
            return

        # Проверяем, является ли пользователь участником чата
        is_participant = await self._is_participant(self.user, self.chat_id)
        if not is_participant:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        logger.info(f'User {self.user.id} connected to chat {self.chat_id}')

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({'error': 'Некорректный JSON'}))
            return

        content = data.get('content', '').strip()
        if not content:
            await self.send(text_data=json.dumps({'error': 'Пустое сообщение'}))
            return

        message = await self._save_message(self.user, self.chat_id, content)
        if not message:
            await self.send(text_data=json.dumps({'error': 'Не удалось сохранить сообщение'}))
            return

        # Рассылаем всем участникам чата
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message,
            }
        )

    async def chat_message(self, event):
        """Отправляем сообщение клиенту."""
        await self.send(text_data=json.dumps(event['message'], ensure_ascii=False, default=str))

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    @database_sync_to_async
    def _is_participant(self, user, chat_id):
        from .models import Chat
        return Chat.objects.filter(id=chat_id, participants=user).exists()

    @database_sync_to_async
    def _save_message(self, user, chat_id, content):
        from .models import Chat, Message
        from django.utils import timezone

        try:
            chat = Chat.objects.get(id=chat_id, participants=user)
        except Chat.DoesNotExist:
            return None

        message = Message.objects.create(
            chat=chat,
            sender=user,
            content=content,
        )
        # Обновляем updated_at чата
        chat.updated_at = timezone.now()
        chat.save(update_fields=['updated_at'])

        return {
            'id': message.id,
            'chat_id': chat.id,
            'sender_id': user.id,
            'sender_name': user.get_full_name(),
            'content': message.content,
            'is_read': message.is_read,
            'created_at': message.created_at.isoformat(),
        }
