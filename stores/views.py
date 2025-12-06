# apps/stores/views.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Views для stores согласно ТЗ v2.0.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. Инвентарь скрыт при статусе "В пути" (требование #11)
2. Удалён фильтр по долгу (требование #5)
3. Добавлена пагинация

API ENDPOINTS:
1. Регионы и города (админ):
   - GET /api/regions/ - список регионов
   - POST /api/regions/ - создать регион
   - GET /api/cities/ - список городов
   - POST /api/cities/ - создать город

2. Магазины:
   - GET /api/stores/ - список магазинов (с поиском и фильтрацией)
   - POST /api/stores/ - регистрация магазина
   - GET /api/stores/{id}/ - детальная информация
   - PATCH /api/stores/{id}/ - обновление профиля
   - POST /api/stores/{id}/approve/ - одобрить (админ)
   - POST /api/stores/{id}/reject/ - отклонить (админ)
   - POST /api/stores/{id}/freeze/ - заморозить (админ)
   - POST /api/stores/{id}/unfreeze/ - разморозить (админ)

3. Выбор магазина:
   - GET /api/stores/available/ - доступные магазины для выбора
   - POST /api/stores/select/ - выбрать магазин
   - POST /api/stores/deselect/ - отменить выбор
   - GET /api/stores/current/ - текущий выбранный магазин

4. Инвентарь:
   - GET /api/stores/{id}/inventory/ - инвентарь магазина
"""

from decimal import Decimal
from typing import Any, Dict

from django.db.models import QuerySet
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from .models import (
    Region,
    City,
    Store,
    StoreSelection,
    StoreInventory,
)
from .serializers import (
    RegionSerializer,
    CitySerializer,
    StoreSerializer,
    StoreListSerializer,
    StoreCreateSerializer,
    StoreUpdateSerializer,
    StoreSelectionSerializer,
    StoreSelectionCreateSerializer,
    StoreInventorySerializer,
    StoreInventoryListSerializer,
    StoreSearchSerializer,
    StoreApproveSerializer,
    StoreRejectSerializer,
    StoreFreezeSerializer,
)
from .services import (
    StoreService,
    StoreSelectionService,
    StoreInventoryService,
    GeographyService,
    BonusCalculationService,  # ✅ НОВОЕ v2.0
    StoreCreateData,
    StoreUpdateData,
    StoreSearchFilters,
)
from .permissions import IsAdmin, IsStore, IsAdminOrReadOnly


# =============================================================================
# PAGINATION
# =============================================================================

class StandardPagination(PageNumberPagination):
    """Стандартная пагинация."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# =============================================================================
# ГЕОГРАФИЯ (РЕГИОНЫ И ГОРОДА)
# =============================================================================

class RegionViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления регионами (только админ).

    ТЗ v2.0: "Области и города управляются админом"
    """

    queryset = Region.objects.all()
    serializer_class = RegionSerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = StandardPagination

    def perform_create(self, serializer):
        """Создание региона через сервис."""
        region = GeographyService.create_region(
            name=serializer.validated_data['name'],
            created_by=self.request.user
        )
        serializer.instance = region


class CityViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления городами (только админ).

    ТЗ v2.0: "Города управляются админом"
    """

    queryset = City.objects.select_related('region').all()
    serializer_class = CitySerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = StandardPagination
    filterset_fields = ['region']

    def perform_create(self, serializer):
        """Создание города через сервис."""
        city = GeographyService.create_city(
            region_id=serializer.validated_data['region'].id,
            name=serializer.validated_data['name'],
            created_by=self.request.user
        )
        serializer.instance = city


# =============================================================================
# МАГАЗИНЫ
# =============================================================================

class StoreViewSet(viewsets.ModelViewSet):
    """
    ViewSet для работы с магазинами.

    ДОСТУП:
    - Админ: все операции
    - Партнёр: чтение, поиск, фильтрация
    - Магазин: регистрация, обновление своего профиля, чтение
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self) -> QuerySet[Store]:
        """Получение списка магазинов в зависимости от роли."""
        user = self.request.user

        if user.role == 'admin':
            queryset = Store.objects.all()

        elif user.role == 'partner':
            queryset = Store.objects.filter(
                approval_status=Store.ApprovalStatus.APPROVED,
                is_active=True
            )

        elif user.role == 'store':
            current_store = StoreSelectionService.get_current_store(user)
            if current_store:
                queryset = Store.objects.filter(pk=current_store.pk)
            else:
                queryset = Store.objects.none()

        else:
            queryset = Store.objects.none()

        return queryset.select_related('region', 'city').order_by('-created_at')

    def get_serializer_class(self):
        """Выбор сериализатора в зависимости от action."""
        if self.action == 'list':
            return StoreListSerializer
        elif self.action == 'create':
            return StoreCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return StoreUpdateSerializer
        return StoreSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        """Регистрация нового магазина."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = StoreCreateData(
            name=serializer.validated_data['name'],
            inn=serializer.validated_data['inn'],
            owner_name=serializer.validated_data['owner_name'],
            phone=serializer.validated_data['phone'],
            region_id=serializer.validated_data['region'].id,
            city_id=serializer.validated_data['city'].id,
            address=serializer.validated_data['address'],
            latitude=serializer.validated_data.get('latitude'),
            longitude=serializer.validated_data.get('longitude'),
        )

        store = StoreService.create_store(
            data=data,
            created_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        """Обновление профиля магазина."""
        store = self.get_object()
        user = request.user

        if user.role == 'store':
            current_store = StoreSelectionService.get_current_store(user)
            if not current_store or current_store.id != store.id:
                return Response(
                    {'error': 'Вы можете редактировать только свой магазин'},
                    status=status.HTTP_403_FORBIDDEN
                )

        partial = kwargs.pop('partial', False)
        serializer = self.get_serializer(store, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        data = StoreUpdateData(
            name=serializer.validated_data.get('name'),
            owner_name=serializer.validated_data.get('owner_name'),
            phone=serializer.validated_data.get('phone'),
            region_id=serializer.validated_data.get('region').id if 'region' in serializer.validated_data else None,
            city_id=serializer.validated_data.get('city').id if 'city' in serializer.validated_data else None,
            address=serializer.validated_data.get('address'),
            latitude=serializer.validated_data.get('latitude'),
            longitude=serializer.validated_data.get('longitude'),
        )

        store = StoreService.update_store(
            store=store,
            data=data,
            updated_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    @action(detail=False, methods=['get'], url_path='search')
    def search(self, request: Request) -> Response:
        """
        Поиск и фильтрация магазинов (ТЗ v2.0).

        GET /api/stores/search/?search=123&region_id=1

        ИЗМЕНЕНИЕ v2.0: Убран фильтр по долгу (требование #5)
        
        Параметры:
        - search: Поиск по ИНН, названию, городу
        - region_id: Фильтр по региону
        - city_id: Фильтр по городу
        - is_active: Только активные / заблокированные
        - approval_status: Статус одобрения
        """
        search_serializer = StoreSearchSerializer(data=request.query_params)
        search_serializer.is_valid(raise_exception=True)

        # ✅ ИЗМЕНЕНИЕ v2.0: Убраны has_debt, min_debt, max_debt
        filters = StoreSearchFilters(
            search_query=search_serializer.validated_data.get('search'),
            region_id=search_serializer.validated_data.get('region_id'),
            city_id=search_serializer.validated_data.get('city_id'),
            is_active=search_serializer.validated_data.get('is_active'),
            approval_status=search_serializer.validated_data.get('approval_status'),
        )

        stores = StoreService.search_stores(filters)

        page = self.paginate_queryset(stores)
        if page is not None:
            serializer = StoreListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreListSerializer(stores, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='debtors')
    def debtors(self, request: Request) -> Response:
        """
        Список магазинов с долгом (от большего к меньшему).

        GET /api/stores/debtors/
        """
        stores = StoreService.get_stores_by_debt_desc()

        page = self.paginate_queryset(stores)
        if page is not None:
            serializer = StoreListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreListSerializer(stores, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='approve', permission_classes=[IsAdmin])
    def approve(self, request: Request, pk=None) -> Response:
        """Одобрить магазин (только админ)."""
        store = self.get_object()

        serializer = StoreApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        store = StoreService.approve_store(
            store=store,
            approved_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    @action(detail=True, methods=['post'], url_path='reject', permission_classes=[IsAdmin])
    def reject(self, request: Request, pk=None) -> Response:
        """Отклонить магазин (только админ)."""
        store = self.get_object()

        serializer = StoreRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        store = StoreService.reject_store(
            store=store,
            rejected_by=request.user,
            reason=serializer.validated_data['reason']
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    @action(detail=True, methods=['post'], url_path='freeze', permission_classes=[IsAdmin])
    def freeze(self, request: Request, pk=None) -> Response:
        """Заморозить магазин (только админ)."""
        store = self.get_object()

        serializer = StoreFreezeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        store = StoreService.freeze_store(
            store=store,
            frozen_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    @action(detail=True, methods=['post'], url_path='unfreeze', permission_classes=[IsAdmin])
    def unfreeze(self, request: Request, pk=None) -> Response:
        """Разморозить магазин (только админ)."""
        store = self.get_object()

        store = StoreService.unfreeze_store(
            store=store,
            unfrozen_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    @action(detail=True, methods=['get'], url_path='inventory')
    def inventory(self, request: Request, pk=None) -> Response:
        """
        Инвентарь магазина.

        GET /api/stores/{id}/inventory/

        КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ v2.0 (требование #11):
        - Магазин НЕ видит инвентарь, пока есть заказы со статусом "В пути"
        - Инвентарь становится виден только после статуса "Принят"
        """
        store = self.get_object()
        user = request.user

        # ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ v2.0: Проверка для магазина
        if user.role == 'store':
            # Импортируем здесь чтобы избежать circular import
            from orders.models import StoreOrder, StoreOrderStatus
            
            # Проверяем есть ли заказы со статусом IN_TRANSIT
            has_in_transit = StoreOrder.objects.filter(
                store=store,
                status=StoreOrderStatus.IN_TRANSIT
            ).exists()
            
            if has_in_transit:
                return Response(
                    {
                        'error': 'Инвентарь недоступен',
                        'message': 'У вас есть заказы в статусе "В пути". '
                                   'Инвентарь станет доступен после подтверждения заказов партнёром.'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        inventory = StoreInventoryService.get_inventory(store)

        page = self.paginate_queryset(inventory)
        if page is not None:
            serializer = StoreInventoryListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreInventoryListSerializer(inventory, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='inventory-with-bonuses')
    def inventory_with_bonuses(self, request: Request, pk=None) -> Response:
        """
        Инвентарь магазина с расчётом бонусов (ТЗ v2.0).

        GET /api/stores/{id}/inventory-with-bonuses/

        ЛОГИКА БОНУСОВ:
        - Каждый 21-й товар бесплатно (20 платных + 1 бонусный)
        - Бонусы только для штучных товаров с is_bonus=True
        - Бонусы считаются по НАКОПЛЕННОМУ количеству в инвентаре

        ПРИМЕР:
        - Товар "Мороженое" (is_bonus=True)
        - Заказ #1: 15 шт, Заказ #2: 10 шт → Инвентарь: 25
        - Бонусы = 25 // 21 = 1 бонусный
        - Платных = 25 - 1 = 24 шт
        """
        store = self.get_object()
        user = request.user

        # Проверка для магазина: инвентарь скрыт при IN_TRANSIT
        if user.role == 'store':
            from orders.models import StoreOrder, StoreOrderStatus
            
            has_in_transit = StoreOrder.objects.filter(
                store=store,
                status=StoreOrderStatus.IN_TRANSIT
            ).exists()
            
            if has_in_transit:
                return Response(
                    {
                        'error': 'Инвентарь недоступен',
                        'message': 'У вас есть заказы в статусе "В пути". '
                                   'Инвентарь станет доступен после подтверждения заказов партнёром.'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        # Получаем инвентарь с бонусами
        inventory_data = BonusCalculationService.get_inventory_with_bonuses(store)
        summary = BonusCalculationService.get_total_bonuses_summary(store)

        return Response({
            'store_id': store.id,
            'store_name': store.name,
            'inventory': inventory_data,
            'bonus_summary': summary
        })


# =============================================================================
# ВЫБОР МАГАЗИНА
# =============================================================================

class AvailableStoresView(APIView):
    """
    Список доступных магазинов для выбора (только для role='store').

    GET /api/stores/available/
    """

    permission_classes = [IsAuthenticated, IsStore]

    def get(self, request: Request) -> Response:
        """Получить все доступные магазины."""
        stores = StoreSelectionService.get_available_stores(request.user)

        serializer = StoreListSerializer(stores, many=True)
        return Response(serializer.data)


class SelectStoreView(APIView):
    """
    Выбрать магазин для работы (только для role='store').

    POST /api/stores/select/
    Body: {"store_id": 1}
    """

    permission_classes = [IsAuthenticated, IsStore]

    def post(self, request: Request) -> Response:
        """Выбрать магазин."""
        serializer = StoreSelectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        selection = StoreSelectionService.select_store(
            user=request.user,
            store_id=serializer.validated_data['store_id']
        )

        output_serializer = StoreSelectionSerializer(selection)
        return Response(output_serializer.data, status=status.HTTP_200_OK)


class DeselectStoreView(APIView):
    """
    Отменить выбор текущего магазина (только для role='store').

    POST /api/stores/deselect/
    """

    permission_classes = [IsAuthenticated, IsStore]

    def post(self, request: Request) -> Response:
        """Отменить выбор магазина."""
        deselected = StoreSelectionService.deselect_store(request.user)

        if deselected:
            return Response(
                {'message': 'Выбор магазина отменён'},
                status=status.HTTP_200_OK
            )

        return Response(
            {'message': 'Активный магазин не найден'},
            status=status.HTTP_404_NOT_FOUND
        )


class CurrentStoreView(APIView):
    """
    Получить текущий выбранный магазин (только для role='store').

    GET /api/stores/current/
    """

    permission_classes = [IsAuthenticated, IsStore]

    def get(self, request: Request) -> Response:
        """Получить текущий магазин."""
        store = StoreSelectionService.get_current_store(request.user)

        if not store:
            return Response(
                {'message': 'Магазин не выбран. Выберите магазин для работы.'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = StoreSerializer(store)
        return Response(serializer.data)


# =============================================================================
# ФУНКЦИОНАЛЬНЫЕ VIEWS
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsStore])
def get_current_store_profile(request: Request) -> Response:
    """
    Профиль текущего магазина пользователя.

    GET /api/stores/profile/
    """
    store = StoreSelectionService.get_current_store(request.user)

    if not store:
        return Response(
            {'error': 'Магазин не выбран'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = StoreSerializer(store)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_users_in_store(request: Request, pk: int) -> Response:
    """
    Список пользователей, работающих в магазине.

    GET /api/stores/{id}/users/
    """
    try:
        store = Store.objects.get(pk=pk)
    except Store.DoesNotExist:
        return Response(
            {'error': 'Магазин не найден'},
            status=status.HTTP_404_NOT_FOUND
        )

    users = StoreSelectionService.get_users_in_store(store)

    users_data = [
        {
            'id': user.id,
            'full_name': user.get_full_name(),
            'email': user.email,
            'phone': user.phone
        }
        for user in users
    ]

    return Response({
        'store_id': store.id,
        'store_name': store.name,
        'users_count': len(users_data),
        'users': users_data
    })
