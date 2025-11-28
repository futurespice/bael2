# apps/stores/views.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db.models import Q, Sum, F
from django.db import transaction
from decimal import Decimal
from datetime import datetime, date
import uuid
from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import (
    Region, City, Store, StoreSelection,
    StoreProductRequest, StoreRequest, StoreRequestItem,
    StoreInventory, PartnerInventory, ReturnRequest, ReturnRequestItem
)
from .serializers import (
    RegionSerializer, CitySerializer, StoreSerializer, StoreSelectionSerializer,
    StoreProductRequestSerializer, CreateStoreRequestSerializer,
    StoreRequestSerializer, StoreInventorySerializer,
    PartnerInventorySerializer, ReturnRequestSerializer,
    # Новые сериализаторы для профиля
    StoreProfileSerializer, StoreProfileUpdateSerializer,
    AddToWishlistSerializer, RemoveFromWishlistSerializer, StoreDebtSerializer
)
from .services import StoreRequestService, InventoryService, StoreProfileService
from users.permissions import IsAdminUser, IsPartnerUser, IsStoreUser
from products.models import Product, BonusHistory, DefectiveProduct
from products.serializers import BonusHistorySerializer, DefectiveProductSerializer
from .filters import StoreFilter


# ============= REGION & CITY =============

class RegionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Регионы Кыргызстана.

    GET /regions/ - список регионов с городами
    GET /regions/{id}/ - детали региона
    """
    queryset = Region.objects.all().prefetch_related('cities')
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticated]


class CityViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Города с фильтрацией по регионам.

    GET /cities/ - все города
    GET /cities/?region={region_id} - города региона
    """
    queryset = City.objects.select_related('region')
    serializer_class = CitySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['region']
    search_fields = ['name']


# ============= STORE (ADMIN CRUD) =============

@extend_schema_view(
    list=extend_schema(summary="Список магазинов"),
    retrieve=extend_schema(summary="Детали магазина"),
    create=extend_schema(summary="Создать магазин"),
    update=extend_schema(summary="Обновить магазин"),
    partial_update=extend_schema(summary="Частично обновить магазин"),
    destroy=extend_schema(summary="Удалить магазин"),
)
class StoreViewSet(viewsets.ModelViewSet):
    """
    Магазины (полный CRUD для админа).

    - Админ видит все магазины
    - Партнёр видит только одобренные активные
    - Store-пользователь видит свои выбранные + одобренные
    """
    queryset = Store.objects.select_related('region', 'city', 'created_by')
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = StoreFilter
    search_fields = ['name', 'inn', 'owner_name', 'phone']
    ordering_fields = ['created_at', 'name', 'debt']
    ordering = ['-created_at']

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated(), IsStoreUser()]
        elif self.action in ['update', 'partial_update', 'destroy', 'approve', 'reject', 'freeze', 'unfreeze']:
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if user.role == 'admin':
            return queryset
        elif user.role == 'store':
            base_qs = queryset.filter(approval_status='approved', is_active=True)
            selected_stores = StoreSelection.objects.filter(user=user).values_list('store_id', flat=True)
            return base_qs | queryset.filter(id__in=selected_stores)
        elif user.role == 'partner':
            return queryset.filter(approval_status='approved', is_active=True)
        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if user.role != 'store':
            raise ValidationError('Только пользователи с ролью STORE могут создавать магазины')

        store = serializer.save(
            created_by=user,
            approval_status='pending'
        )
        StoreSelection.objects.create(user=user, store=store)

    @extend_schema(summary="Одобрить магазин")
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        """Одобрить магазин (только админ)"""
        store = self.get_object()
        store.approval_status = 'approved'
        store.is_active = True
        store.save(update_fields=['approval_status', 'is_active'])
        return Response({'status': 'approved', 'store_id': store.id})

    @extend_schema(summary="Отклонить магазин")
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        """Отклонить магазин (только админ)"""
        store = self.get_object()
        store.approval_status = 'rejected'
        store.is_active = False
        store.save(update_fields=['approval_status', 'is_active'])
        return Response({'status': 'rejected', 'store_id': store.id})

    @extend_schema(summary="Заморозить магазин")
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def freeze(self, request, pk=None):
        """
        Заморозить магазин (деактивировать).
        После заморозки партнёры не могут взаимодействовать с магазином.
        """
        store = self.get_object()
        store.is_active = False
        store.save(update_fields=['is_active'])
        return Response({
            'status': 'frozen',
            'store_id': store.id,
            'message': 'Магазин заморожен. Взаимодействие недоступно.'
        })

    @extend_schema(summary="Разморозить магазин")
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def unfreeze(self, request, pk=None):
        """Разморозить магазин (активировать)"""
        store = self.get_object()
        if store.approval_status != 'approved':
            return Response(
                {'error': 'Нельзя разморозить неодобренный магазин'},
                status=status.HTTP_400_BAD_REQUEST
            )
        store.is_active = True
        store.save(update_fields=['is_active'])
        return Response({
            'status': 'active',
            'store_id': store.id,
            'message': 'Магазин активен.'
        })

    @extend_schema(summary="Магазины ожидающие одобрения")
    @action(detail=False, methods=['get'], permission_classes=[IsAdminUser])
    def pending(self, request):
        """Список магазинов ожидающих одобрения"""
        queryset = Store.objects.filter(approval_status='pending')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(summary="Статистика по магазинам")
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Общая статистика по магазинам"""
        queryset = self.get_queryset()
        return Response({
            'total_stores': queryset.count(),
            'active_stores': queryset.filter(is_active=True).count(),
            'pending_stores': queryset.filter(approval_status='pending').count(),
            'total_debt': queryset.aggregate(Sum('debt'))['debt__sum'] or 0
        })


# ============= STORE PROFILE (для роли STORE после selection) =============

@extend_schema_view(
    retrieve=extend_schema(summary="Получить профиль текущего магазина"),
    update=extend_schema(summary="Обновить профиль магазина"),
    partial_update=extend_schema(summary="Частично обновить профиль"),
)
class StoreProfileViewSet(mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin,
                          viewsets.GenericViewSet):
    """
    Профиль текущего выбранного магазина.

    Endpoints:
    - GET /stores/profile/ - получить профиль
    - PUT /stores/profile/ - полное обновление
    - PATCH /stores/profile/ - частичное обновление
    - GET /stores/profile/debt/ - информация о долге
    - GET /stores/profile/statistics/ - статистика магазина
    - GET /stores/profile/wishlist/ - wishlist магазина
    - POST /stores/profile/wishlist/add/ - добавить в wishlist
    - DELETE /stores/profile/wishlist/remove/ - удалить из wishlist
    - DELETE /stores/profile/wishlist/clear/ - очистить wishlist
    """
    permission_classes = [IsAuthenticated, IsStoreUser]

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return StoreProfileUpdateSerializer
        return StoreProfileSerializer

    def get_object(self):
        """Получить текущий выбранный магазин"""
        store = StoreProfileService.get_current_store(self.request.user)
        if not store:
            raise ValidationError('Магазин не выбран. Сначала выберите магазин через /selection/')

        # Проверяем permissions
        self.check_object_permissions(self.request, store)
        return store

    @extend_schema(summary="Получить профиль магазина")
    def retrieve(self, request, *args, **kwargs):
        """GET /stores/profile/ - профиль текущего магазина"""
        store = self.get_object()
        serializer = self.get_serializer(store)
        return Response(serializer.data)

    @extend_schema(summary="Обновить профиль магазина")
    def update(self, request, *args, **kwargs):
        """PUT /stores/profile/ - полное обновление профиля"""
        partial = kwargs.pop('partial', False)
        store = self.get_object()

        # Проверка заморозки
        if not store.is_active:
            return Response(
                {'error': 'Магазин заморожен. Редактирование недоступно.'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.get_serializer(store, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_store = StoreProfileService.update_store_profile(
                request.user, serializer.validated_data
            )
            return Response(StoreProfileSerializer(updated_store).data)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, *args, **kwargs):
        """PATCH /stores/profile/ - частичное обновление"""
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    # === DEBT INFO ===

    @extend_schema(summary="Информация о долге магазина")
    @action(detail=False, methods=['get'])
    def debt(self, request):
        """GET /stores/profile/debt/ - текущий долг магазина"""
        store = self.get_object()

        from orders.models import StoreOrder, DebtPayment

        # Получаем историю долгов по заказам
        orders_with_debt = StoreOrder.objects.filter(
            store=store,
            debt_amount__gt=0
        ).select_related('partner').order_by('-created_at')

        orders_data = []
        for order in orders_with_debt[:10]:  # Последние 10
            orders_data.append({
                'order_id': order.id,
                'total_amount': str(order.total_amount),
                'debt_amount': str(order.debt_amount),
                'paid_amount': str(order.paid_amount),
                'outstanding': str(order.outstanding_debt),
                'created_at': order.created_at.isoformat()
            })

        return Response({
            'store_id': store.id,
            'store_name': store.name,
            'total_debt': str(store.debt),
            'recent_orders_with_debt': orders_data
        })

    # === STATISTICS ===

    @extend_schema(
        summary="Статистика магазина",
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.DATE, description='Дата начала периода'),
            OpenApiParameter('date_to', OpenApiTypes.DATE, description='Дата окончания периода'),
        ]
    )
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """GET /stores/profile/statistics/ - статистика магазина за период"""
        store = self.get_object()

        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        if date_from:
            date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        if date_to:
            date_to = datetime.strptime(date_to, '%Y-%m-%d').date()

        stats = StoreProfileService.get_store_statistics(store, date_from, date_to)

        return Response({
            'store_id': store.id,
            'store_name': store.name,
            'period': {
                'from': date_from.isoformat() if date_from else None,
                'to': date_to.isoformat() if date_to else None
            },
            'statistics': {
                'total_orders': stats['total_orders'],
                'total_amount': str(stats['total_amount']),
                'total_debt': str(stats['total_debt']),
                'total_paid': str(stats['total_paid']),
                'outstanding_debt': str(stats['outstanding_debt']),
                'bonus_count': stats['bonus_count'],
                'bonus_quantity': str(stats['bonus_quantity']),
                'wishlist_items': stats['wishlist_items']
            }
        })

    # === WISHLIST OPERATIONS ===

    @extend_schema(summary="Получить wishlist магазина")
    @action(detail=False, methods=['get'])
    def wishlist(self, request):
        """GET /stores/profile/wishlist/ - текущий wishlist"""
        try:
            wishlist_data = StoreRequestService.get_wishlist(request.user)
            serializer = StoreProductRequestSerializer(wishlist_data['items'], many=True)

            return Response({
                'store_id': wishlist_data['store_id'],
                'store_name': wishlist_data['store_name'],
                'items': serializer.data,
                'total_items': wishlist_data['total_items'],
                'total_amount': str(wishlist_data['total_amount'])
            })
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Добавить товар в wishlist",
        request=AddToWishlistSerializer
    )
    @action(detail=False, methods=['post'], url_path='wishlist/add')
    def wishlist_add(self, request):
        """POST /stores/profile/wishlist/add/ - добавить товар"""
        serializer = AddToWishlistSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            product_request = StoreRequestService.add_to_wishlist(
                user=request.user,
                product=serializer.validated_data['product'],
                quantity=serializer.validated_data['quantity']
            )
            return Response({
                'status': 'added',
                'item': StoreProductRequestSerializer(product_request).data
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Удалить товар из wishlist",
        request=RemoveFromWishlistSerializer
    )
    @action(detail=False, methods=['delete'], url_path='wishlist/remove')
    def wishlist_remove(self, request):
        """DELETE /stores/profile/wishlist/remove/ - удалить товар"""
        serializer = RemoveFromWishlistSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            removed = StoreRequestService.remove_from_wishlist(
                user=request.user,
                product=serializer.validated_data['product']
            )
            if removed:
                return Response({'status': 'removed'}, status=status.HTTP_204_NO_CONTENT)
            return Response({'error': 'Товар не найден в wishlist'}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(summary="Очистить весь wishlist")
    @action(detail=False, methods=['delete'], url_path='wishlist/clear')
    def wishlist_clear(self, request):
        """DELETE /stores/profile/wishlist/clear/ - очистить wishlist"""
        try:
            count = StoreRequestService.clear_wishlist(request.user)
            return Response({
                'status': 'cleared',
                'deleted_count': count
            }, status=status.HTTP_204_NO_CONTENT)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Создать запрос из wishlist",
        request=CreateStoreRequestSerializer
    )
    @action(detail=False, methods=['post'], url_path='wishlist/submit')
    @transaction.atomic
    def wishlist_submit(self, request):
        """
        POST /stores/profile/wishlist/submit/ - создать запрос из wishlist.
        Переносит все товары из wishlist в StoreRequest.
        """
        serializer = CreateStoreRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        idempotency_key = serializer.validated_data.get('idempotency_key') or str(uuid.uuid4())
        note = serializer.validated_data.get('note', '')

        # Проверяем idempotency
        existing = StoreRequest.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return Response(
                StoreRequestSerializer(existing).data,
                status=status.HTTP_200_OK
            )

        store = StoreProfileService.get_current_store(request.user)
        if not store:
            return Response(
                {'error': 'Магазин не выбран.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not store.is_active:
            return Response(
                {'error': 'Магазин заморожен. Операции недоступны.'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            store_request = StoreRequestService.create_from_product_requests(
                store=store,
                user=request.user,
                note=note,
                idempotency_key=idempotency_key
            )
            return Response(
                StoreRequestSerializer(store_request).data,
                status=status.HTTP_201_CREATED
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============= STORE SELECTION =============

@extend_schema_view(
    list=extend_schema(summary="Список выбранных магазинов"),
    create=extend_schema(summary="Выбрать магазин"),
    destroy=extend_schema(summary="Отменить выбор магазина"),
)
class StoreSelectionViewSet(viewsets.ModelViewSet):
    """
    Выбор магазина пользователем (роль STORE).

    Поддерживает множественный выбор магазинов.
    Текущий магазин - последний выбранный.
    """
    serializer_class = StoreSelectionSerializer
    permission_classes = [IsAuthenticated, IsStoreUser]
    http_method_names = ['get', 'post', 'delete']

    def get_queryset(self):
        return StoreSelection.objects.filter(
            user=self.request.user
        ).select_related('store', 'store__region', 'store__city').order_by('-selected_at')

    def perform_create(self, serializer):
        store = serializer.validated_data['store']
        if store.approval_status != 'approved':
            raise ValidationError({'store': 'Магазин должен быть одобрен для выбора.'})
        if not store.is_active:
            raise ValidationError({'store': 'Магазин заморожен.'})
        serializer.save(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        current = queryset.first()
        return Response({
            'count': queryset.count(),
            'current_store': {
                'id': current.store.id,
                'name': current.store.name,
                'inn': current.store.inn
            } if current else None,
            'selections': serializer.data
        })

    @extend_schema(summary="Текущий выбранный магазин")
    @action(detail=False, methods=['get'])
    def current(self, request):
        """GET /selection/current/ - получить текущий магазин"""
        selection = self.get_queryset().first()
        if not selection:
            return Response(
                {'error': 'Магазин не выбран'},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response({
            'selection_id': selection.id,
            'store': StoreSerializer(selection.store).data,
            'selected_at': selection.selected_at
        })

    @extend_schema(summary="Выйти из всех магазинов")
    @action(detail=False, methods=['delete'])
    def clear(self, request):
        """DELETE /selection/clear/ - выйти из всех магазинов"""
        count, _ = self.get_queryset().delete()
        return Response({
            'status': 'cleared',
            'deleted_count': count
        }, status=status.HTTP_204_NO_CONTENT)


# ============= STORE PRODUCT REQUESTS (Legacy) =============

class StoreProductRequestViewSet(viewsets.ModelViewSet):
    """
    Запросы на товары магазина (wishlist).
    DEPRECATED: Используйте /stores/profile/wishlist/ endpoints.
    """
    serializer_class = StoreProductRequestSerializer
    permission_classes = [IsAuthenticated, IsStoreUser]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return StoreProductRequest.objects.all().select_related('product', 'store')

        store = StoreProfileService.get_current_store(user)
        if store:
            return StoreProductRequest.objects.filter(store=store).select_related('product')
        return StoreProductRequest.objects.none()

    @transaction.atomic
    def perform_create(self, serializer):
        store = StoreProfileService.get_current_store(self.request.user)
        if not store:
            raise ValidationError('Магазин не выбран.')
        if not store.is_active:
            raise ValidationError('Магазин заморожен.')
        serializer.save(store=store)


# ============= STORE REQUESTS =============

@extend_schema_view(
    list=extend_schema(summary="История запросов магазина"),
    retrieve=extend_schema(summary="Детали запроса"),
)
class StoreRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """
    История запросов магазина (snapshots wishlist).
    Только чтение. Создание через /stores/profile/wishlist/submit/.
    """
    queryset = StoreRequest.objects.select_related(
        'store', 'created_by'
    ).prefetch_related('items__product')
    serializer_class = StoreRequestSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['store', 'created_at']
    search_fields = ['store__name', 'note']
    ordering_fields = ['created_at', 'total_amount']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if user.role == 'admin':
            return queryset
        elif user.role == 'store':
            store = StoreProfileService.get_current_store(user)
            if store:
                return queryset.filter(store=store)
            return queryset.none()
        elif user.role == 'partner':
            return queryset.filter(
                store__approval_status='approved',
                store__is_active=True
            )
        return queryset.none()

    @extend_schema(summary="Отменить позицию в запросе")
    @action(detail=True, methods=['post'], permission_classes=[IsStoreUser])
    @transaction.atomic
    def cancel_item(self, request, pk=None):
        """POST /requests/{id}/cancel_item/ - отменить позицию"""
        store_request = self.get_object()
        store = StoreProfileService.get_current_store(request.user)

        if store_request.store != store:
            return Response({'error': 'Доступ запрещён'}, status=status.HTTP_403_FORBIDDEN)

        item_id = request.data.get('item_id')
        if not item_id:
            return Response({'error': 'item_id обязателен'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            StoreRequestService.cancel_item(store_request, item_id)
            return Response({'status': 'cancelled'})
        except (ValidationError, StoreRequestItem.DoesNotExist) as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============= INVENTORY =============

class StoreInventoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Инвентарь магазина (только чтение)"""
    serializer_class = StoreInventorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return StoreInventory.objects.select_related('store', 'product')
        elif user.role == 'store':
            store = StoreProfileService.get_current_store(user)
            if store:
                return StoreInventory.objects.filter(store=store).select_related('product')
        return StoreInventory.objects.none()


class PartnerInventoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Инвентарь партнёра (только чтение)"""
    serializer_class = PartnerInventorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return PartnerInventory.objects.select_related('partner', 'product')
        elif user.role == 'partner':
            return PartnerInventory.objects.filter(partner=user).select_related('product')
        return PartnerInventory.objects.none()


# ============= RETURN REQUESTS =============

class ReturnRequestViewSet(viewsets.ModelViewSet):
    """Запросы на возврат товаров партнером к админу"""
    serializer_class = ReturnRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ['approve', 'reject']:
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated(), IsPartnerUser()]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return ReturnRequest.objects.all().select_related('partner', 'store')
        return ReturnRequest.objects.filter(partner=user).select_related('store')

    @transaction.atomic
    def perform_create(self, serializer):
        idempotency_key = self.request.data.get('idempotency_key') or str(uuid.uuid4())
        serializer.save(
            partner=self.request.user,
            idempotency_key=idempotency_key
        )

    @extend_schema(summary="Подтвердить возврат")
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        """Подтвердить возврат (только админ)"""
        return_request = self.get_object()

        if return_request.status != 'pending':
            return Response(
                {'error': 'Запрос уже обработан'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Списываем у партнёра и возвращаем на общий склад
        for item in return_request.items.all():
            InventoryService.remove_from_inventory(
                partner=return_request.partner,
                product=item.product,
                quantity=item.quantity
            )
            # Возвращаем на общий склад
            item.product.stock_quantity += item.quantity
            item.product.save(update_fields=['stock_quantity'])

        return_request.status = 'approved'
        return_request.save(update_fields=['status'])

        return Response({'status': 'approved'})

    @extend_schema(summary="Отклонить возврат")
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Отклонить возврат"""
        return_request = self.get_object()

        if return_request.status != 'pending':
            return Response(
                {'error': 'Запрос уже обработан'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return_request.status = 'rejected'
        return_request.save(update_fields=['status'])

        return Response({'status': 'rejected'})
