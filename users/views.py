# apps/users/views.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Views для управления пользователями.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. remember_me теперь сохраняет access токен на 3 месяца (90 дней)
2. Все пользователи автоматически одобряются
"""

from rest_framework import status, generics, viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django_filters.rest_framework import DjangoFilterBackend
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import random
import string

from .models import User, PasswordResetRequest
from .serializers import (
    UserRegistrationSerializer,
    LoginSerializer,
    UserProfileSerializer,
    AdminUserListSerializer,
    UserModerationSerializer,
    PasswordResetRequestSerializer,
    PasswordResetCodeSerializer,
    PasswordResetConfirmSerializer,
)
from .permissions import IsAdminUser
from .throttles import LoginThrottle, PasswordResetThrottle, RegistrationThrottle


class UserRegistrationView(generics.CreateAPIView):
    """
    Регистрация пользователей с автоматическим определением роли по маркеру.
    
    POST /api/auth/register/
    
    Body:
    {
        "name": "Иван",
        "second_name": "Иванов",
        "email": "ivan@example.com",
        "phone": "+996700000001",
        "password": "mypassword123"
    }
    
    Если в пароле есть маркер партнёра (p!8Rt), роль = partner.
    Иначе роль = store.
    
    ВАЖНО: Все пользователи автоматически одобряются (approval_status='approved').
    
    RATE LIMITING: 10 регистраций в час с одного IP
    """

    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]
    throttle_classes = [RegistrationThrottle]  # ✅ Rate Limiting

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Формируем ответ
        response_data = {
            'message': 'Регистрация успешна. Вы можете войти в систему.',
            'user': {
                'id': user.id,
                'phone': user.phone,
                'email': user.email,
                'name': user.name,
                'second_name': user.second_name,
                'role': user.role,
                'approval_status': user.approval_status,
                'is_active': user.is_active
            }
        }

        return Response(response_data, status=status.HTTP_201_CREATED)


class LoginView(generics.CreateAPIView):
    """
    Вход в систему.
    
    POST /api/auth/login/
    
    Body:
    {
        "phone": "+996700000001",
        "password": "mypassword123",
        "remember_me": true
    }
    
    RATE LIMITING: 5 попыток в минуту (защита от brute-force)
    
    КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ v2.0:
    - Если remember_me=true, access токен действует 90 дней (3 месяца)
    """

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]  # ✅ Rate Limiting

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        remember_me = serializer.validated_data.get('remember_me', False)

        # Обновляем время последнего входа
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        # Генерируем токены
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: remember_me на 3 месяца (по требованию #8)
        if remember_me:
            # Access токен на 90 дней (3 месяца)
            access.set_exp(lifetime=timedelta(days=90))
            # Refresh токен тоже на 90 дней
            refresh.set_exp(lifetime=timedelta(days=90))

        return Response({
            'access': str(access),
            'refresh': str(refresh),
            'remember_me': remember_me,
            'token_lifetime_days': 90 if remember_me else 1,
            'user': {
                'id': user.id,
                'phone': user.phone,
                'email': user.email,
                'name': user.name,
                'second_name': user.second_name,
                'role': user.role,
                'full_name': user.full_name,
                'approval_status': user.approval_status,
                'is_active': user.is_active
            }
        })


class LogoutView(generics.CreateAPIView):
    """
    Выход из системы - добавление токена в blacklist.
    
    POST /api/auth/logout/
    
    Body:
    {
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    }
    """

    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()

            return Response({
                'message': 'Успешный выход из системы'
            }, status=status.HTTP_200_OK)

        except Exception:
            return Response({
                'message': 'Выход выполнен (токен был недействителен)'
            }, status=status.HTTP_200_OK)


class LogoutAllDevicesView(generics.CreateAPIView):
    """
    Выход изо всех устройств (ТЗ v2.0).
    
    POST /api/auth/logout-all/
    
    Инвалидирует все токены пользователя.
    """

    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        from .services import TokenService
        
        count = TokenService.blacklist_all_user_tokens(request.user)

        return Response({
            'message': 'Вы вышли изо всех устройств',
            'tokens_invalidated': count
        }, status=status.HTTP_200_OK)


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    Просмотр и редактирование профиля.
    
    GET /api/auth/profile/ - получение профиля
    PUT /api/auth/profile/ - полное обновление профиля
    PATCH /api/auth/profile/ - частичное обновление профиля
    """

    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class AdminUserViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления пользователями (только админ).
    
    GET /api/auth/admin/users/ - список пользователей
    GET /api/auth/admin/users/{id}/ - детали пользователя
    PATCH /api/auth/admin/users/{id}/approve/ - одобрить
    PATCH /api/auth/admin/users/{id}/reject/ - отклонить
    PATCH /api/auth/admin/users/{id}/block/ - заблокировать
    PATCH /api/auth/admin/users/{id}/unblock/ - разблокировать
    """

    queryset = User.objects.all()
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['role', 'approval_status', 'is_active']
    search_fields = ['email', 'phone', 'name', 'second_name']
    ordering_fields = ['created_at', 'last_login', 'email']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return AdminUserListSerializer
        elif self.action in ['approve', 'reject', 'block', 'unblock']:
            return UserModerationSerializer
        return UserProfileSerializer

    @action(detail=True, methods=['patch'])
    def approve(self, request, pk=None):
        """Одобрение пользователя администратором."""
        user = self.get_object()
        user.approval_status = 'approved'
        user.save(update_fields=['approval_status'])

        return Response({
            'message': f'Пользователь {user.full_name} одобрен',
            'user': AdminUserListSerializer(user).data
        })

    @action(detail=True, methods=['patch'])
    def reject(self, request, pk=None):
        """Отклонение пользователя администратором."""
        user = self.get_object()
        user.approval_status = 'rejected'
        user.save(update_fields=['approval_status'])

        return Response({
            'message': f'Пользователь {user.full_name} отклонён',
            'user': AdminUserListSerializer(user).data
        })

    @action(detail=True, methods=['patch'])
    def block(self, request, pk=None):
        """
        Блокировка пользователя.
        
        ТЗ v2.0: При блокировке все токены пользователя должны быть инвалидированы.
        """
        from .services import TokenService
        
        user = self.get_object()
        if user.role == 'admin':
            return Response(
                {'error': 'Нельзя заблокировать администратора'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_active = False
        user.save(update_fields=['is_active'])
        
        # ✅ ИСПРАВЛЕНИЕ v2.0: Инвалидируем все токены пользователя
        tokens_invalidated = TokenService.blacklist_all_user_tokens(user)

        return Response({
            'message': f'Пользователь {user.full_name} заблокирован',
            'tokens_invalidated': tokens_invalidated,
            'user': AdminUserListSerializer(user).data
        })

    @action(detail=True, methods=['patch'])
    def unblock(self, request, pk=None):
        """Разблокировка пользователя."""
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=['is_active'])

        return Response({
            'message': f'Пользователь {user.full_name} разблокирован',
            'user': AdminUserListSerializer(user).data
        })

    @action(detail=False, methods=['get'])
    def pending_approval(self, request):
        """Список пользователей, ожидающих одобрения."""
        pending_users = User.objects.filter(approval_status='pending')
        serializer = AdminUserListSerializer(pending_users, many=True)
        return Response({
            'count': pending_users.count(),
            'results': serializer.data
        })

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Статистика пользователей."""
        total_users = User.objects.count()
        partners = User.objects.filter(role='partner').count()
        stores = User.objects.filter(role='store').count()
        pending = User.objects.filter(approval_status='pending').count()
        blocked = User.objects.filter(is_active=False).count()

        return Response({
            'total_users': total_users,
            'partners': partners,
            'stores': stores,
            'pending_approval': pending,
            'blocked_users': blocked
        })


class PasswordResetRequestView(generics.CreateAPIView):
    """
    Запрос сброса пароля - отправка 5-значного кода на email.
    
    POST /api/auth/password/reset/
    
    Body:
    {
        "email": "user@example.com"
    }
    
    RATE LIMITING: 3 запроса в час (защита от спама)
    """

    serializer_class = PasswordResetRequestSerializer
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]  # ✅ Rate Limiting

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        user = User.objects.get(email=email)

        # Генерируем 5-значный код
        code = ''.join(random.choices(string.digits, k=5))

        # Удаляем старые неиспользованные коды
        PasswordResetRequest.objects.filter(user=user, is_used=False).delete()

        # Создаем новый запрос
        reset_request = PasswordResetRequest.objects.create(
            user=user,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        # Отправляем email
        try:
            send_mail(
                subject='Код сброса пароля - БайЭл',
                message=f'Ваш код для сброса пароля: {code}\nКод действителен 15 минут.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )

            return Response({
                'message': 'Код отправлен на ваш email',
                'email': email
            })

        except Exception:
            reset_request.delete()
            return Response(
                {'error': 'Ошибка отправки email'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PasswordResetCodeVerifyView(generics.CreateAPIView):
    """
    Проверка 5-значного кода.
    
    POST /api/auth/password/verify/
    
    Body:
    {
        "email": "user@example.com",
        "code": "12345"
    }
    """

    serializer_class = PasswordResetCodeSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return Response({
            'message': 'Код подтвержден',
            'email': serializer.validated_data['email'],
            'code': serializer.validated_data['code']
        })


class PasswordResetConfirmView(generics.CreateAPIView):
    """
    Установка нового пароля.
    
    POST /api/auth/password/confirm/
    
    Body:
    {
        "email": "user@example.com",
        "code": "12345",
        "new_password": "newpassword123",
        "new_password_confirm": "newpassword123"
    }
    """

    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        from .services import TokenService
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        reset_request = serializer.validated_data['reset_request']
        new_password = serializer.validated_data['new_password']

        # Устанавливаем новый пароль
        user.set_password(new_password)
        user.save()

        # Помечаем запрос как использованный
        reset_request.is_used = True
        reset_request.save()
        
        # ✅ ИСПРАВЛЕНИЕ v2.0: Инвалидируем все старые токены
        TokenService.blacklist_all_user_tokens(user)

        return Response({
            'message': 'Пароль успешно изменен'
        })
