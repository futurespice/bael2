from django.contrib.auth.models import BaseUserManager
from django.conf import settings

# Маркер партнёра из настроек
PARTNER_MARKER = getattr(settings, 'PARTNER_MARKER', 'p!8Rt')


class UserManager(BaseUserManager):
    """Менеджер пользователей с логикой определения роли по маркеру"""

    def _extract_role_from_password(self, password):
        """Определяет роль по наличию маркера в пароле"""
        if PARTNER_MARKER in password:
            return 'partner'
        return 'store'

    def _clean_password_from_marker(self, password):
        """Удаляет маркер из пароля перед сохранением"""
        return password.replace(PARTNER_MARKER, '')

    def create_user(self, phone, email, password=None, **extra_fields):
        """Создает пользователя с автоматическим определением роли"""
        if not phone:
            raise ValueError('Номер телефона обязателен')
        if not email:
            raise ValueError('Email обязателен')
        if not password:
            raise ValueError('Пароль обязателен')

        # Нормализуем email
        email = self.normalize_email(email)

        # Определяем роль по маркеру в пароле
        role = self._extract_role_from_password(password)
        extra_fields.setdefault('role', role)

        # Очищаем пароль от маркера
        clean_password = self._clean_password_from_marker(password)

        # Партнёры требуют одобрения администратора
        if role == 'partner':
            extra_fields.setdefault('approval_status', 'pending')
        else:
            extra_fields.setdefault('approval_status', 'approved')

        # Создаем пользователя
        user = self.model(phone=phone, email=email, **extra_fields)
        user.set_password(clean_password)
        user.save(using=self._db)

        return user

    def create_superuser(self, phone, email, password=None, **extra_fields):
        """Создает суперпользователя (администратора)"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('approval_status', 'approved')
        extra_fields.setdefault('role', 'admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Суперпользователь должен иметь is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Суперпользователь должен иметь is_superuser=True')

        # Для суперпользователя не применяем логику маркеров
        user = self.model(phone=phone, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user
