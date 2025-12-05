# apps/orders/permissions.py
"""Permissions для orders."""

from rest_framework import permissions


class IsAdmin(permissions.BasePermission):
    """Только администраторы."""

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


class IsStore(permissions.BasePermission):
    """Только магазины."""

    def has_permission(self, request, view):
        return (
                request.user and
                request.user.is_authenticated and
                request.user.role == 'store'
        )