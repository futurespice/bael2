from rest_framework import permissions


class IsAdminOnly(permissions.BasePermission):
    """Только админ или суперюзер"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Суперюзер всегда проходит
        if request.user.is_superuser:
            return True

        # Или роль admin (строчная)
        return hasattr(request.user, 'role') and request.user.role == 'admin'


class IsPartnerOrAdmin(permissions.BasePermission):
    """Партнёр или админ"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        return hasattr(request.user, 'role') and request.user.role in ['partner', 'admin']