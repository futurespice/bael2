# apps/products/permissions.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Permissions для products.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. Добавлен IsPartner
2. Добавлен IsPartnerOrAdmin
"""

from rest_framework import permissions


class IsAdmin(permissions.BasePermission):
    """Только админы."""

    def has_permission(self, request, view):
        return (
                request.user and
                request.user.is_authenticated and
                request.user.role == 'admin'
        )


class IsPartner(permissions.BasePermission):
    """Только партнёры."""

    def has_permission(self, request, view):
        return (
                request.user and
                request.user.is_authenticated and
                request.user.role == 'partner'
        )


class IsPartnerOrAdmin(permissions.BasePermission):
    """
    Партнёры или админы.
    
    Используется для:
    - PartnerExpenseViewSet (партнёр создаёт, админ видит всё)
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.role in ['admin', 'partner']


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Админы: полный доступ
    Партнёры и магазины: только чтение
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Админ: полный доступ
        if request.user.role == 'admin':
            return True

        # Партнёры и магазины: только чтение
        if request.user.role in ['partner', 'store']:
            return request.method in permissions.SAFE_METHODS

        return False
