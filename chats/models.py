from django.conf import settings
from django.db import models


class Chat(models.Model):
    """Чат между двумя пользователями."""

    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='chats',
        verbose_name='Участники'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создан')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлён')

    class Meta:
        db_table = 'chats'
        verbose_name = 'Чат'
        verbose_name_plural = 'Чаты'
        ordering = ['-updated_at']

    def __str__(self):
        users = ', '.join(str(u) for u in self.participants.all())
        return f'Чат [{users}]'

    def get_other_participant(self, user):
        return self.participants.exclude(id=user.id).first()

    @property
    def unread_count(self):
        return self.messages.filter(is_read=False).count()


class Message(models.Model):
    """Сообщение в чате."""

    chat = models.ForeignKey(
        Chat,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Чат'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages',
        verbose_name='Отправитель'
    )
    content = models.TextField(verbose_name='Текст')
    is_read = models.BooleanField(default=False, verbose_name='Прочитано')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Отправлено')

    class Meta:
        db_table = 'chat_messages'
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.sender} → {self.chat_id}: {self.content[:50]}'
