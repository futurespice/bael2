"""
JWT WebSocket middleware.

Извлекает JWT токен из query string (?token=...) и аутентифицирует пользователя.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

User = get_user_model()


@database_sync_to_async
def get_user_from_token(token: str):
    try:
        from rest_framework_simplejwt.tokens import UntypedToken
        from rest_framework_simplejwt.backends import TokenBackend
        from django.conf import settings

        UntypedToken(token)  # Проверка валидности

        backend = TokenBackend(
            algorithm=settings.SIMPLE_JWT.get('ALGORITHM', 'HS256'),
            signing_key=settings.SECRET_KEY,
        )
        data = backend.decode(token, verify=True)
        user_id = data.get('user_id')
        return User.objects.get(id=user_id, is_active=True)
    except Exception:
        return AnonymousUser()


class JWTAuthMiddleware:
    """ASGI middleware для JWT аутентификации через WebSocket."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('websocket', 'http'):
            query_string = scope.get('query_string', b'').decode()
            params = parse_qs(query_string)
            token_list = params.get('token', [])

            if token_list:
                scope['user'] = await get_user_from_token(token_list[0])
            else:
                scope['user'] = AnonymousUser()

        return await self.app(scope, receive, send)
