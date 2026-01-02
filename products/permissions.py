# apps/products/permissions.py
"""Permissions для products (БЕЗ ИЗМЕНЕНИЙ)."""

from rest_framework import permissions


class IsAdmin(permissions.BasePermission):
    """Только админ."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'admin'


class IsPartner(permissions.BasePermission):
    """Только партнёр."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'partner'


class IsStore(permissions.BasePermission):
    """Только магазин."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'store'


class IsAdminOrPartner(permissions.BasePermission):
    """Админ или партнёр."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ['admin', 'partner']