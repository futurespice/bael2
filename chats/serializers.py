from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Chat, Message

User = get_user_model()


class UserShortSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'full_name', 'phone', 'role', 'avatar']

    def get_full_name(self, obj):
        return obj.get_full_name()


class MessageSerializer(serializers.ModelSerializer):
    sender = UserShortSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'chat', 'sender', 'content', 'is_read', 'created_at']
        read_only_fields = ['id', 'chat', 'sender', 'is_read', 'created_at']


class ChatSerializer(serializers.ModelSerializer):
    other_participant = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = ['id', 'other_participant', 'last_message', 'unread_count', 'updated_at']

    def get_other_participant(self, obj):
        request = self.context.get('request')
        if request:
            other = obj.get_other_participant(request.user)
            if other:
                return UserShortSerializer(other).data
        return None

    def get_last_message(self, obj):
        last = obj.messages.last()
        if last:
            return {
                'id': last.id,
                'content': last.content,
                'sender_id': last.sender_id,
                'created_at': last.created_at,
                'is_read': last.is_read,
            }
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request:
            return obj.messages.filter(is_read=False).exclude(sender=request.user).count()
        return 0


class CreateChatSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()

    def validate_user_id(self, value):
        request = self.context['request']
        current_user = request.user

        try:
            target_user = User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError('Пользователь не найден.')

        if target_user == current_user:
            raise serializers.ValidationError('Нельзя создать чат с самим собой.')

        # Правила доступа
        if not self._can_chat(current_user, target_user):
            raise serializers.ValidationError(
                'Магазины могут общаться только с партнёрами и администраторами.'
            )

        return value

    def _can_chat(self, user1, user2):
        """
        store ↔ partner: разрешено
        store ↔ admin:   разрешено
        store ↔ store:   запрещено
        partner/admin ↔ все: разрешено
        """
        roles = {user1.role, user2.role}
        if 'store' in roles and roles == {'store'}:
            return False
        return True

    def create(self, validated_data):
        request = self.context['request']
        current_user = request.user
        target_user = User.objects.get(id=validated_data['user_id'])

        # Ищем существующий чат между двумя пользователями
        existing_chat = (
            Chat.objects.filter(participants=current_user)
            .filter(participants=target_user)
            .first()
        )
        if existing_chat:
            return existing_chat

        chat = Chat.objects.create()
        chat.participants.add(current_user, target_user)
        return chat
