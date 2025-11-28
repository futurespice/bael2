# apps/users/models.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Кастомная модель пользователя с поддержкой ролей через маркер"""

    ROLE_CHOICES = [
        ('admin', 'Администратор'),
        ('partner', 'Партнёр'),
        ('store', 'Магазин'),
    ]

    APPROVAL_STATUS_CHOICES = [
        ('pending', 'В процессе'),
        ('approved', 'Одобрен'),
        ('rejected', 'Отказано'),
    ]

    # Валидаторы
    email_validator = RegexValidator(
        regex=r'^[^@]+@[^@]+\.[^@]+$',
        message='Email должен содержать ровно один символ @ и быть корректным'
    )

    phone_validator = RegexValidator(
        regex=r'^\+996\d{9}$',
        message='Номер телефона должен быть в формате +996XXXXXXXXX'
    )

    # Основные поля
    email = models.EmailField(
        max_length=50,
        unique=True,
        validators=[email_validator],
        verbose_name='Email'
    )
    phone = models.CharField(
        max_length=13,  # +996XXXXXXXXX = 13 символов
        unique=True,
        validators=[phone_validator],
        verbose_name='Телефон'
    )
    name = models.CharField(max_length=100, verbose_name='Имя')
    second_name = models.CharField(max_length=100, verbose_name='Фамилия')

    # Роль и статусы
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='store', verbose_name='Роль')
    approval_status = models.CharField(
        max_length=10,
        choices=APPROVAL_STATUS_CHOICES,
        default='approved',  # Магазины автоматически одобряются
        verbose_name='Статус одобрения'
    )
    is_active = models.BooleanField(default=True, verbose_name='Активен (не заблокирован)')
    is_staff = models.BooleanField(default=False, verbose_name='Персонал')

    # Дополнительные поля
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, verbose_name='Фото')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    last_login = models.DateTimeField(blank=True, null=True, verbose_name='Последний вход')

    objects = UserManager()

    USERNAME_FIELD = 'phone'  # Вход по номеру телефона
    REQUIRED_FIELDS = ['email', 'name', 'second_name']

    class Meta:
        db_table = 'users'
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_full_name()} ({self.phone})"

    def get_full_name(self):
        """Возвращает полное имя пользователя"""
        return f"{self.name} {self.second_name}".strip()

    def get_short_name(self):
        """Возвращает короткое имя пользователя"""
        return self.name

    @property
    def full_name(self):
        """Свойство для полного имени"""
        return self.get_full_name()

    @property
    def is_approved(self):
        """Совместимость со старым кодом"""
        return self.approval_status == 'approved'

    def save(self, *args, **kwargs):
        """Переопределение сохранения"""
        # Администраторы автоматически становятся персоналом
        if self.role == 'admin':
            self.is_staff = True
            self.approval_status = 'approved'

        super().save(*args, **kwargs)


class PasswordResetRequest(models.Model):
    """Запросы на сброс пароля с 5-значным кодом"""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name='Пользователь'
    )
    code = models.CharField(max_length=5, verbose_name='5-значный код')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    expires_at = models.DateTimeField(verbose_name='Истекает')
    is_used = models.BooleanField(default=False, verbose_name='Использован')

    class Meta:
        db_table = 'password_reset_requests'
        verbose_name = 'Запрос сброса пароля'
        verbose_name_plural = 'Запросы сброса пароля'
        ordering = ['-created_at']

    def __str__(self):
        return f"Сброс пароля для {self.user.email} - {self.code}"

    def is_valid(self):
        """Проверка действительности кода"""
        return (
                not self.is_used and
                timezone.now() < self.expires_at
        )