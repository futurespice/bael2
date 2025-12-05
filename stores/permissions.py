# apps/stores/permissions.py
"""
Пермишены для stores согласно ТЗ v2.0.
"""

from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView


class IsAdmin(permissions.BasePermission):
    """Только администраторы."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return (
                request.user and
                request.user.is_authenticated and
                request.user.role == 'admin'
        )


class IsPartner(permissions.BasePermission):
    """Только партнёры."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return (
                request.user and
                request.user.is_authenticated and
                request.user.role == 'partner'
        )


class IsStore(permissions.BasePermission):
    """Только пользователи с ролью магазин."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return (
                request.user and
                request.user.is_authenticated and
                request.user.role == 'store'
        )


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Админ: все операции
    Остальные: только чтение
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        # Чтение доступно всем
        if request.method in permissions.SAFE_METHODS:
            return True

        # Изменение только для админа
        return request.user.role == 'admin'


class IsStoreOwnerOrAdmin(permissions.BasePermission):
    """
    Проверка доступа к магазину:
    - Админ: полный доступ
    - Магазин: доступ только к своему магазину
    """

    def has_object_permission(self, request: Request, view: APIView, obj) -> bool:
        # Админ имеет полный доступ
        if request.user.role == 'admin':
            return True

        # Магазин может редактировать только свой профиль
        if request.user.role == 'store':
            from .services import StoreSelectionService
            current_store = StoreSelectionService.get_current_store(request.user)
            return current_store and current_store.id == obj.id

        return False