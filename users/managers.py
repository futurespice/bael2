# apps/users/managers.py
"""
Менеджер пользователей с логикой определения роли по маркеру.

ИЗМЕНЕНИЯ v2.0:
- Все пользователи автоматически одобряются после регистрации
- Маркер партнёра определяет роль, но не влияет на approval_status
"""

from django.contrib.auth.models import BaseUserManager
from django.conf import settings

# Маркер партнёра из настроек
PARTNER_MARKER = getattr(settings, 'PARTNER_MARKER', 'p!8Rt')


class UserManager(BaseUserManager):
    """
    Менеджер пользователей с логикой определения роли по маркеру.
    
    ВАЖНО (ТЗ v2.0):
    - ВСЕ пользователи автоматически получают approval_status='approved'
    - Маркер в пароле определяет только роль (partner/store)
    """

    def _extract_role_from_password(self, password: str) -> str:
        """
        Определяет роль по наличию маркера в пароле.
        
        Args:
            password: Пароль пользователя
            
        Returns:
            'partner' если маркер найден, иначе 'store'
        """
        if PARTNER_MARKER in password:
            return 'partner'
        return 'store'

    def _clean_password_from_marker(self, password: str) -> str:
        """
        Удаляет маркер из пароля перед сохранением.
        
        Args:
            password: Пароль с возможным маркером
            
        Returns:
            Очищенный пароль
        """
        return password.replace(PARTNER_MARKER, '')

    def create_user(
        self, 
        phone: str, 
        email: str, 
        password: str = None, 
        **extra_fields
    ):
        """
        Создает пользователя с автоматическим определением роли.
        
        ВАЖНО (ТЗ v2.0):
        - ВСЕ пользователи автоматически одобряются (approval_status='approved')
        - Роль определяется по маркеру в пароле
        
        Args:
            phone: Номер телефона (+996XXXXXXXXX)
            email: Email пользователя
            password: Пароль (может содержать маркер партнёра)
            **extra_fields: Дополнительные поля
            
        Returns:
            User: Созданный пользователь
            
        Raises:
            ValueError: Если обязательные поля не указаны
        """
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

        # ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: ВСЕ пользователи автоматически одобряются
        # По требованию #1: "Все пользователи после регистрации автоматически проходят регистрацию"
        extra_fields['approval_status'] = 'approved'

        # Создаем пользователя
        user = self.model(phone=phone, email=email, **extra_fields)
        user.set_password(clean_password)
        user.save(using=self._db)

        return user

    def create_superuser(
        self, 
        phone: str, 
        email: str, 
        password: str = None, 
        **extra_fields
    ):
        """
        Создает суперпользователя (администратора).
        
        Args:
            phone: Номер телефона
            email: Email
            password: Пароль
            **extra_fields: Дополнительные поля
            
        Returns:
            User: Созданный суперпользователь
        """
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
