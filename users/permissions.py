from rest_framework.permissions import BasePermission


class IsAdminUser(BasePermission):
    """Разрешение только для администраторов"""

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'admin'
        )


class IsPartnerUser(BasePermission):
    """Разрешение только для партнёров"""

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'partner' and
            request.user.approval_status == 'approved'
        )


class IsStoreUser(BasePermission):
    """Разрешение только для магазинов"""

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'store' and
            request.user.approval_status == 'approved'
        )


class IsApprovedUser(BasePermission):
    """Разрешение только для одобренных пользователей"""

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.approval_status == 'approved'
        )


class IsOwnerOrAdmin(BasePermission):
    """Разрешение для владельца объекта или администратора"""

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated
        )

    def has_object_permission(self, request, view, obj):
        # Администраторы имеют доступ ко всему
        if request.user.role == 'admin':
            return True

        # Проверяем владельца в зависимости от типа объекта
        if hasattr(obj, 'user'):
            return obj.user == request.user
        elif hasattr(obj, 'store') and hasattr(obj.store, 'user'):
            return obj.store.user == request.user
        elif hasattr(obj, 'partner'):
            return obj.partner == request.user

        return False
