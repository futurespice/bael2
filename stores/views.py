# apps/stores/views.py - ПОЛНАЯ ВЕРСИЯ v2.0 (ЧАСТЬ 1/2)
"""
Views для stores согласно ТЗ v2.0.

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
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

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
    StoreCreateData,
    StoreUpdateData,
    StoreSearchFilters,
)
from .permissions import IsAdmin, IsStore, IsAdminOrReadOnly


# =============================================================================
# ГЕОГРАФИЯ (РЕГИОНЫ И ГОРОДА)
# =============================================================================

class RegionViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления регионами (только админ).

    ТЗ v2.0: "Области и города управляются админом (добавление,
    редактирование, удаление)"
    """

    queryset = Region.objects.all()
    serializer_class = RegionSerializer
    permission_classes = [IsAdminOrReadOnly]

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

    ENDPOINTS:
    - GET /api/stores/ - список магазинов
    - POST /api/stores/ - регистрация магазина
    - GET /api/stores/{id}/ - детальная информация
    - PATCH /api/stores/{id}/ - обновление профиля
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Store]:
        """
        Получение списка магазинов в зависимости от роли.

        - Админ: все магазины
        - Партнёр: только одобренные и активные
        - Магазин: только свой выбранный магазин
        """
        user = self.request.user

        if user.role == 'admin':
            # Админ видит все магазины
            queryset = Store.objects.all()

        elif user.role == 'partner':
            # Партнёр видит только одобренные и активные
            queryset = Store.objects.filter(
                approval_status=Store.ApprovalStatus.APPROVED,
                is_active=True
            )

        elif user.role == 'store':
            # Магазин видит только свой текущий магазин
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
        """
        Регистрация нового магазина (ТЗ v2.0, раздел 1.4).

        POST /api/stores/

        Body:
        {
            "name": "Мой магазин",
            "inn": "123456789012",
            "owner_name": "Иванов Иван",
            "phone": "+996700000001",
            "region": 1,
            "city": 1,
            "address": "ул. Ленина, 1"
        }
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Создаём магазин через сервис
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

        # Возвращаем полную информацию
        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        """
        Обновление профиля магазина.

        PATCH /api/stores/{id}/

        Доступ:
        - Админ: любой магазин
        - Магазин: только свой профиль
        """
        store = self.get_object()
        user = request.user

        # Проверка доступа
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

        # Обновляем через сервис
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

        GET /api/stores/search/?search=123&region_id=1&has_debt=true

        Параметры:
        - search: Поиск по ИНН, названию, городу
        - region_id: Фильтр по региону
        - city_id: Фильтр по городу
        - has_debt: Только с долгом / без долга
        - is_active: Только активные / заблокированные
        - approval_status: Статус одобрения
        - min_debt: Минимальный долг
        - max_debt: Максимальный долг
        """
        # Валидация параметров
        search_serializer = StoreSearchSerializer(data=request.query_params)
        search_serializer.is_valid(raise_exception=True)

        # Формируем фильтры
        filters = StoreSearchFilters(
            search_query=search_serializer.validated_data.get('search'),
            region_id=search_serializer.validated_data.get('region_id'),
            city_id=search_serializer.validated_data.get('city_id'),
            has_debt=search_serializer.validated_data.get('has_debt'),
            is_active=search_serializer.validated_data.get('is_active'),
            approval_status=search_serializer.validated_data.get('approval_status'),
            min_debt=search_serializer.validated_data.get('min_debt'),
            max_debt=search_serializer.validated_data.get('max_debt'),
        )

        # Поиск через сервис
        stores = StoreService.search_stores(filters)

        # Пагинация
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

        ТЗ: "Сортировка должников от большего к меньшему"
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
        """
        Одобрить магазин (только админ).

        POST /api/stores/{id}/approve/

        Body (опционально):
        {
            "comment": "Магазин одобрен"
        }
        """
        store = self.get_object()

        serializer = StoreApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Одобряем через сервис
        store = StoreService.approve_store(
            store=store,
            approved_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    @action(detail=True, methods=['post'], url_path='reject', permission_classes=[IsAdmin])
    def reject(self, request: Request, pk=None) -> Response:
        """
        Отклонить магазин (только админ).

        POST /api/stores/{id}/reject/

        Body:
        {
            "reason": "Неверные данные"
        }
        """
        store = self.get_object()

        serializer = StoreRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Отклоняем через сервис
        store = StoreService.reject_store(
            store=store,
            rejected_by=request.user,
            reason=serializer.validated_data['reason']
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    @action(detail=True, methods=['post'], url_path='freeze', permission_classes=[IsAdmin])
    def freeze(self, request: Request, pk=None) -> Response:
        """
        Заморозить магазин (только админ).

        POST /api/stores/{id}/freeze/

        ТЗ: "При заморозке партнёры не могут с магазином взаимодействовать"
        """
        store = self.get_object()

        serializer = StoreFreezeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Замораживаем через сервис
        store = StoreService.freeze_store(
            store=store,
            frozen_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    @action(detail=True, methods=['post'], url_path='unfreeze', permission_classes=[IsAdmin])
    def unfreeze(self, request: Request, pk=None) -> Response:
        """
        Разморозить магазин (только админ).

        POST /api/stores/{id}/unfreeze/
        """
        store = self.get_object()

        # Размораживаем через сервис
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

        ТЗ: "Все заказы складываются в один инвентарь"
        """
        store = self.get_object()

        inventory = StoreInventoryService.get_inventory(store)

        serializer = StoreInventoryListSerializer(inventory, many=True)
        return Response(serializer.data)


# apps/stores/views.py - ПОЛНАЯ ВЕРСИЯ v2.0 (ЧАСТЬ 2/2)
"""
Views для выбора магазина и инвентаря.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Store
from .serializers import (
    StoreListSerializer,
    StoreSerializer,
    StoreSelectionSerializer,
    StoreSelectionCreateSerializer,
)
from .services import StoreSelectionService
from .permissions import IsStore


# =============================================================================
# ВЫБОР МАГАЗИНА
# =============================================================================

class AvailableStoresView(APIView):
    """
    Список доступных магазинов для выбора (только для role='store').

    GET /api/stores/available/

    ТЗ: "Общая база магазинов для всех пользователей role='store'"
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

    ТЗ: "Один пользователь может быть только в одном магазине одновременно.
    Несколько пользователей могут быть в одном магазине."

    Body:
    {
        "store_id": 1
    }
    """

    permission_classes = [IsAuthenticated, IsStore]

    def post(self, request: Request) -> Response:
        """Выбрать магазин."""
        serializer = StoreSelectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Выбираем магазин через сервис
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

    ТЗ: "Пользователь может выйти и переключиться на другой магазин"
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

    Возвращает полную информацию о текущем магазине пользователя.
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
# ФУНКЦИОНАЛЬНЫЕ VIEWS (ПРОСТЫЕ)
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsStore])
def get_current_store_profile(request: Request) -> Response:
    """
    Профиль текущего магазина пользователя.

    GET /api/stores/profile/

    ТЗ: "После выбора магазина доступен CRUD профиля через /stores/profile/"

    Алиас для /api/stores/current/
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

    ТЗ: "Несколько пользователей могут быть в одном магазине одновременно"
    """
    try:
        store = Store.objects.get(pk=pk)
    except Store.DoesNotExist:
        return Response(
            {'error': 'Магазин не найден'},
            status=status.HTTP_404_NOT_FOUND
        )

    users = StoreSelectionService.get_users_in_store(store)

    # Простой ответ с именами и ID
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