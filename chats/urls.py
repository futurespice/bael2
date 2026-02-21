from django.urls import path
from .views import ChatListCreateView, ChatMessagesView, MarkMessagesReadView, AvailableUsersView

urlpatterns = [
    path('', ChatListCreateView.as_view(), name='chat-list-create'),
    path('users/', AvailableUsersView.as_view(), name='chat-available-users'),
    path('<int:chat_id>/messages/', ChatMessagesView.as_view(), name='chat-messages'),
    path('<int:chat_id>/read/', MarkMessagesReadView.as_view(), name='chat-mark-read'),
]
