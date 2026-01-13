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


class IsStoreOwner(permissions.BasePermission):
    """
    Проверка: пользователь является владельцем магазина.
    
    v3.0: Используется для update/delete операций.
    """
    
    def has_object_permission(self, request, view, obj):
        # Админ может всё
        if request.user.role == 'admin':
            return True
        
        # Владелец магазина может редактировать свой магазин
        if request.user.role == 'store':
            return obj.owner == request.user
        
        return False


class CanAccessStore(permissions.BasePermission):
    """
    Проверка: пользователь может видеть магазин.
    
    v3.0:
    - Админ: все магазины
    - Store: только свои магазины
    - Partner: магазины, с которыми работает
    """
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Админ видит всё
        if user.role == 'admin':
            return True
        
        # Владелец видит свой магазин
        if user.role == 'store' and obj.owner == user:
            return True
        
        # Партнер видит магазины, с которыми работает
        if user.role == 'partner':
            from orders.models import StoreOrder
            return StoreOrder.objects.filter(
                partner=user,
                store=obj
            ).exists()
        
        return False