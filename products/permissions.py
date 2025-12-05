# apps/products/permissions.py
"""Permissions для products."""

from rest_framework import permissions


class IsAdmin(permissions.BasePermission):
    """Только админы."""

    def has_permission(self, request, view):
        return (
                request.user and
                request.user.is_authenticated and
                request.user.role == 'admin'
        )


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