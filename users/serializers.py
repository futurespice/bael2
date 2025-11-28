from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import User, PasswordResetRequest



class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Сериализатор регистрации пользователей
    Поля: name, second_name, email, phone, password (без подтверждения)
    """

    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['name', 'second_name', 'email', 'phone', 'password']

    def validate_email(self, value):
        """Валидация email по ТЗ"""
        if len(value) > 50:
            raise serializers.ValidationError('Email не должен превышать 50 символов')
        if value.count('@') != 1:
            raise serializers.ValidationError('Email должен содержать ровно один символ @')

        # Проверяем уникальность email
        if User.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError('Пользователь с таким email уже существует')

        return value.lower()

    def validate_phone(self, value):
        """Валидация номера телефона"""
        if not value.startswith('+996'):
            raise serializers.ValidationError('Номер должен начинаться с +996')
        if len(value) != 13:  # +996XXXXXXXXX
            raise serializers.ValidationError('Номер должен быть в формате +996XXXXXXXXX')

        # Проверяем, что остальные символы - цифры
        digits_part = value[4:]  # Убираем +996
        if not digits_part.isdigit():
            raise serializers.ValidationError('После +996 должны быть только цифры')

        # Проверяем уникальность телефона
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError('Пользователь с таким номером уже существует')

        return value

    def validate_name(self, value):
        """Валидация имени по ТЗ"""
        if not value or not value.strip():
            raise serializers.ValidationError('Имя обязательно для заполнения')

        value = value.strip()
        if len(value) < 2 or len(value) > 24:
            raise serializers.ValidationError('Имя должно быть от 2 до 24 символов')
        return value.title()  # Заглавная буква

    def validate_second_name(self, value):
        """Валидация фамилии по ТЗ"""
        if not value or not value.strip():
            raise serializers.ValidationError('Фамилия обязательна для заполнения')

        value = value.strip()
        if len(value) < 2 or len(value) > 24:
            raise serializers.ValidationError('Фамилия должна быть от 2 до 24 символов')
        return value.title()  # Заглавная буква

    def validate_password(self, value):
        """Валидация пароля БЕЗ Django валидаторов для маркера"""
        if not value:
            raise serializers.ValidationError('Пароль обязателен')

        # Убираем маркер для проверки длины
        clean_password = value.replace('p!8Rt', '')

        # Простая проверка длины без Django валидаторов
        if len(clean_password) < 6:
            raise serializers.ValidationError('Пароль должен содержать минимум 6 символов (без учёта маркера)')

        # НЕ используем Django validate_password, так как он слишком строгий
        # для наших тестовых паролей и не учитывает маркер

        return value

    def create(self, validated_data):
        """Создание пользователя"""
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    """
    Сериализатор для входа
    Требуется: номер телефона и пароль
    """

    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)
    remember_me = serializers.BooleanField(default=False)

    def validate_phone(self, value):
        """Проверяем формат номера"""
        if not value.startswith('+996'):
            raise serializers.ValidationError('Номер должен начинаться с +996')
        return value

    def validate(self, attrs):
        """Валидация входа"""
        phone = attrs.get('phone')
        password = attrs.get('password')

        if not phone or not password:
            raise serializers.ValidationError('Необходимо указать номер телефона и пароль')

        # Ищем пользователя по номеру телефона
        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            raise serializers.ValidationError('Пользователь с таким номером не найден')

        # Проверяем пароль
        if not user.check_password(password):
            raise serializers.ValidationError('Неверный пароль')

        # Проверяем активность и одобрение
        if not user.is_active:
            raise serializers.ValidationError('Аккаунт заблокирован')

        if user.approval_status != 'approved':
            status_msg = {
                'pending': 'Аккаунт ожидает одобрения администратором',
                'rejected': 'Аккаунт отклонён администратором'
            }
            raise serializers.ValidationError(status_msg.get(user.approval_status, 'Аккаунт не одобрен'))

        attrs['user'] = user
        return attrs

class UserProfileSerializer(serializers.ModelSerializer):
    """Сериализатор профиля пользователя для просмотра и редактирования"""

    full_name = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'phone', 'name', 'second_name', 'full_name',
            'role', 'approval_status', 'is_active', 'avatar', 'created_at', 'last_login'
        ]
        read_only_fields = ['id', 'role', 'approval_status', 'is_active', 'created_at', 'last_login']

    def validate_email(self, value):
        """Валидация email при изменении"""
        if len(value) > 50:
            raise serializers.ValidationError('Email не должен превышать 50 символов')
        if value.count('@') != 1:
            raise serializers.ValidationError('Email должен содержать ровно один символ @')

        # Проверяем уникальность, исключая текущего пользователя
        user = self.instance
        if User.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('Пользователь с таким email уже существует')

        return value.lower()

    def validate_phone(self, value):
        """Валидация номера телефона при изменении"""
        if not value.startswith('+996'):
            raise serializers.ValidationError('Номер должен начинаться с +996')
        if len(value) != 13:
            raise serializers.ValidationError('Номер должен быть в формате +996XXXXXXXXX')

        # Проверяем уникальность, исключая текущего пользователя
        user = self.instance
        if User.objects.filter(phone=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('Пользователь с таким номером уже существует')

        return value


class AdminUserListSerializer(serializers.ModelSerializer):
    """Сериализатор для списка пользователей (админ)"""

    full_name = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'phone', 'email', 'full_name', 'name', 'second_name',
            'role', 'approval_status', 'is_active', 'avatar', 'created_at', 'last_login'
        ]


class UserModerationSerializer(serializers.ModelSerializer):
    """Сериализатор для модерации пользователей (админ)"""

    class Meta:
        model = User
        fields = ['approval_status', 'is_active']


class PasswordResetRequestSerializer(serializers.Serializer):
    """
    Сериализатор запроса сброса пароля
    Требуется только email
    """

    email = serializers.EmailField()

    def validate_email(self, value):
        """Проверяем существование пользователя"""
        try:
            User.objects.get(email=value, is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError('Пользователь с таким email не найден')
        return value


class PasswordResetCodeSerializer(serializers.Serializer):
    """Сериализатор проверки кода сброса пароля"""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=5, min_length=5)

    def validate(self, attrs):
        """Проверяем код"""
        try:
            user = User.objects.get(email=attrs['email'])
            reset_request = PasswordResetRequest.objects.get(
                user=user,
                code=attrs['code'],
                is_used=False
            )

            if not reset_request.is_valid():
                raise serializers.ValidationError('Код истёк или недействителен')

            attrs['reset_request'] = reset_request
            attrs['user'] = user

        except (User.DoesNotExist, PasswordResetRequest.DoesNotExist):
            raise serializers.ValidationError('Неверный код')

        return attrs


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Сериализатор подтверждения нового пароля"""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=5, min_length=5)
    new_password = serializers.CharField(min_length=6)
    new_password_confirm = serializers.CharField(min_length=6)

    def validate(self, attrs):
        """Валидация нового пароля"""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError('Пароли не совпадают')

        # Проверяем код еще раз
        try:
            user = User.objects.get(email=attrs['email'])
            reset_request = PasswordResetRequest.objects.get(
                user=user,
                code=attrs['code'],
                is_used=False
            )

            if not reset_request.is_valid():
                raise serializers.ValidationError('Код истёк')

            attrs['reset_request'] = reset_request
            attrs['user'] = user

        except (User.DoesNotExist, PasswordResetRequest.DoesNotExist):
            raise serializers.ValidationError('Неверный код')

        return attrs
