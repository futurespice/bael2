from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from .views import (
    UserRegistrationView,
    LoginView,
    LogoutView,
    UserProfileView,
    AdminUserViewSet,
    PasswordResetRequestView,
    PasswordResetCodeVerifyView,
    PasswordResetConfirmView,
)

router = DefaultRouter()
router.register(r'admin/users', AdminUserViewSet, basename='admin-users')

app_name = 'users'

urlpatterns = [
    # Регистрация (name, second_name, email, phone, password)
    path('register/', UserRegistrationView.as_view(), name='register'),

    # Вход/Выход (phone, password)
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('verify/', TokenVerifyView.as_view(), name='token_verify'),

    # Сброс пароля (3 этапа по ТЗ)
    # 1. Запрос (только email)
    path('password/reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    # 2. Проверка кода
    path('password/verify/', PasswordResetCodeVerifyView.as_view(), name='password_verify'),
    # 3. Установка нового пароля
    path('password/confirm/', PasswordResetConfirmView.as_view(), name='password_confirm'),

    # Профиль (GET, PUT, PATCH)
    path('profile/', UserProfileView.as_view(), name='profile'),

    # Админские функции
    path('', include(router.urls)),
]

