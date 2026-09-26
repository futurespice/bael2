"""
Логирование каждого HTTP-запроса.

Django сам пишет только 4xx/5xx и без подробностей ("Bad Request: /api/auth/login/").
Этот middleware пишет одну строку на каждый запрос:

    POST /api/auth/login/ 400 35ms user=anon ip=1.2.3.4 | {"phone": ["Неверный номер"]}

Для ответов 4xx/5xx добавляется начало тела ответа, чтобы было видно причину ошибки.
Тело запроса НЕ логируется (там могут быть пароли).
"""
import logging
import time

from asgiref.sync import iscoroutinefunction, markcoroutinefunction

logger = logging.getLogger('baiel.requests')

# Пути, которые не нужно логировать (статика, медиа, healthcheck)
SKIP_PREFIXES = ('/static/', '/media/', '/favicon.ico')

MAX_BODY_LOG = 1000


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '-')


def _user_label(request):
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_authenticated', False):
        return f'{user.pk}'
    return 'anon'


def _error_body(response):
    if getattr(response, 'streaming', False):
        return ''
    content_type = response.get('Content-Type', '')
    if 'json' not in content_type and 'text/plain' not in content_type:
        return ''
    try:
        body = response.content.decode('utf-8', errors='replace')
    except Exception:
        return ''
    body = ' '.join(body.split())
    if len(body) > MAX_BODY_LOG:
        body = body[:MAX_BODY_LOG] + '…'
    return body


def _log(request, response, started):
    path = request.path
    if path.startswith(SKIP_PREFIXES):
        return

    status = response.status_code
    duration_ms = (time.monotonic() - started) * 1000
    query = request.META.get('QUERY_STRING')
    full_path = f'{path}?{query}' if query else path

    message = (
        f'{request.method} {full_path} {status} {duration_ms:.0f}ms '
        f'user={_user_label(request)} ip={_client_ip(request)}'
    )

    if status >= 500:
        level = logging.ERROR
    elif status >= 400:
        level = logging.WARNING
    else:
        level = logging.INFO

    if status >= 400:
        body = _error_body(response)
        if body:
            message = f'{message} | {body}'

    logger.log(level, message)


class RequestLoggingMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self.is_async:
            return self.__acall__(request)
        started = time.monotonic()
        response = self.get_response(request)
        self._safe_log(request, response, started)
        return response

    async def __acall__(self, request):
        started = time.monotonic()
        response = await self.get_response(request)
        self._safe_log(request, response, started)
        return response

    @staticmethod
    def _safe_log(request, response, started):
        try:
            _log(request, response, started)
        except Exception:
            logger.exception('Ошибка при логировании запроса')
