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
)

User = get_user_model()


class ChatListCreateView(APIView):
    """
    GET  /api/chats/         — список чатов текущего пользователя
    POST /api/chats/         — создать (или получить) чат с пользователем
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        chats = (
            Chat.objects.filter(participants=request.user)
            .prefetch_related('participants', 'messages')
            .order_by('-updated_at')
        )

        # Фильтр по роли собеседника: ?role=store | partner | admin
        # Доступен только для admin и partner (store видит всего два типа, фильтр им не нужен)
        role_filter = request.query_params.get('role')
        if role_filter and request.user.role in ('admin', 'partner'):
            valid_roles = {'store', 'partner', 'admin'}
            if role_filter in valid_roles:
                chats = chats.filter(participants__role=role_filter).exclude(
                    participants=request.user
                )
                # После filter/exclude могут появиться дубли — убираем
                chats = chats.distinct()

        serializer = ChatSerializer(chats, many=True, context={'request': request})
        return Response(serializer.data)

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

        serializer = UserShortSerializer(qs, many=True)
        return Response(serializer.data)
