from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from .models import Chat, Message
from .serializers import (
    ChatSerializer,
    CreateChatSerializer,
    MessageSerializer,
    UserShortSerializer,
    UserWithChatSerializer,
)

User = get_user_model()


class ChatListCreateView(APIView):
    """
    GET  /api/chats/         — список чатов текущего пользователя
    POST /api/chats/         — создать (или получить) чат с пользователем
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Роли собеседников в зависимости от роли текущего пользователя
        if user.role == 'store':
            allowed_roles = ['admin', 'partner']
        else:
            allowed_roles = ['admin', 'partner', 'store']

        available_users = list(
            User.objects.exclude(id=user.id)
            .filter(is_active=True, role__in=allowed_roles)
        )

        # Маппинг {other_user_id: chat_id} из уже существующих чатов
        existing_chats = Chat.objects.filter(participants=user).prefetch_related('participants')
        chat_id_map = {}
        for chat in existing_chats:
            for participant in chat.participants.all():
                if participant.id != user.id:
                    chat_id_map[participant.id] = chat.id

        # Авто-создаём чаты для тех, у кого их ещё нет
        for other_user in available_users:
            if other_user.id not in chat_id_map:
                chat = Chat.objects.create()
                chat.participants.add(user, other_user)
                chat_id_map[other_user.id] = chat.id

        # Загружаем все чаты с prefetch
        chats_by_id = {
            c.id: c
            for c in Chat.objects.filter(id__in=chat_id_map.values())
            .prefetch_related('participants', 'messages')
        }

        # Группируем по роли собеседника
        role_key_map = {'admin': 'admins', 'partner': 'partners', 'store': 'stores'}
        result = {role_key_map[r]: [] for r in allowed_roles}

        for other_user in available_users:
            key = role_key_map.get(other_user.role)
            chat = chats_by_id.get(chat_id_map[other_user.id])
            if key and chat:
                result[key].append(ChatSerializer(chat, context={'request': request}).data)

        # Если передан ?role= — возвращаем только эту категорию как плоский список
        role_filter = request.query_params.get('role')
        if role_filter:
            key = role_key_map.get(role_filter)
            if key and key in result:
                return Response(result[key])
            return Response([])

        return Response(result)

    def post(self, request):
        serializer = CreateChatSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        chat = serializer.save()
        return Response(
            ChatSerializer(chat, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )


class ChatMessagesView(APIView):
    """
    GET   /api/chats/{chat_id}/messages/  — история сообщений
    POST  /api/chats/{chat_id}/messages/  — отправить сообщение (REST fallback)
    """
    permission_classes = [IsAuthenticated]

    def _get_chat(self, chat_id, user):
        return get_object_or_404(Chat, id=chat_id, participants=user)

    def get(self, request, chat_id):
        chat = self._get_chat(chat_id, request.user)
        # Помечаем сообщения собеседника как прочитанные
        chat.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)
        messages = chat.messages.select_related('sender').all()
        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data)

    def post(self, request, chat_id):
        chat = self._get_chat(chat_id, request.user)
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(chat=chat, sender=request.user)
        chat.save()  # Обновляем updated_at чата
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class MarkMessagesReadView(APIView):
    """
    POST /api/chats/{chat_id}/read/  — пометить все сообщения в чате как прочитанные
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, chat_id):
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)
        updated = chat.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)
        return Response({'marked_read': updated})


class AvailableUsersView(APIView):
    """
    GET /api/chats/users/  — список пользователей, с которыми можно начать чат.
    Правила:
      - store → может видеть только partner и admin
      - partner/admin → видит всех (кроме себя)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = User.objects.exclude(id=user.id).filter(is_active=True)

        if user.role == 'store':
            qs = qs.filter(role__in=['partner', 'admin'])

        # Строим маппинг {other_user_id: chat_id} для текущего пользователя
        chats = Chat.objects.filter(participants=user).prefetch_related('participants')
        chat_map = {}
        for chat in chats:
            for participant in chat.participants.all():
                if participant.id != user.id:
                    chat_map[participant.id] = chat.id

        # Авто-создаём чаты для тех, у кого их ещё нет
        users_list = list(qs)
        for other_user in users_list:
            if other_user.id not in chat_map:
                chat = Chat.objects.create()
                chat.participants.add(user, other_user)
                chat_map[other_user.id] = chat.id

        serializer = UserWithChatSerializer(users_list, many=True, context={'chat_map': chat_map})
        return Response(serializer.data)
