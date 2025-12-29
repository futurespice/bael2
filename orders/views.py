# apps/orders/views.py - ОЧИЩЕННАЯ ВЕРСИЯ v2.1
"""
Views для orders согласно ТЗ v2.0.

ОЧИСТКА v2.1:
1. УДАЛЁН DefectiveProductViewSet (брак через stores)
2. УДАЛЁН order_history action (дубль my_orders)
3. УДАЛЁН весь закомментированный код
4. Добавлен http_method_names для запрета PUT/PATCH/DELETE
5. Добавлена проверка статуса в approve/reject

API ENDPOINTS:
- GET /api/orders/store-orders/ - список заказов
- POST /api/orders/store-orders/ - создание заказа (магазин)
- GET /api/orders/store-orders/{id}/ - детали заказа
- GET /api/orders/store-orders/my-orders/ - заказы магазина
- POST /api/orders/store-orders/{id}/approve/ - админ одобряет
- POST /api/orders/store-orders/{id}/reject/ - админ отклоняет
"""

from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from stores.models import Store
from stores.services import StoreSelectionService

from .models import (
    StoreOrder,
    StoreOrderStatus,
)
from .serializers import (
    StoreOrderListSerializer,
    StoreOrderDetailSerializer,
    StoreOrderCreateSerializer,
    StoreOrderForStoreSerializer,
    OrderApproveSerializer,
    OrderRejectSerializer,
)
from .services import (
    OrderWorkflowService,
    OrderItemData,
)
from .permissions import IsAdmin, IsPartner, IsStore


# =============================================================================
# PAGINATION
# =============================================================================

class StandardPagination(PageNumberPagination):
    """Стандартная пагинация."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# =============================================================================
# STORE ORDER VIEWSET
# =============================================================================

class StoreOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet для заказов магазинов (ТЗ v2.0).

    ДОСТУП:
    - Админ: все заказы, approve/reject
    - Партнёр: только IN_TRANSIT (для информации)
    - Магазин: создание заказа, свои заказы

    API:
    - GET /api/orders/store-orders/ - список
    - POST /api/orders/store-orders/ - создание (магазин)
    - GET /api/orders/store-orders/{id}/ - детали
    - GET /api/orders/store-orders/my-orders/ - мои заказы (магазин)
    - POST /api/orders/store-orders/{id}/approve/ - одобрить (админ)
    - POST /api/orders/store-orders/{id}/reject/ - отклонить (админ)

    ВАЖНО (ТЗ v2.0):
    - Магазин НЕ может редактировать заказ после создания
    - Подтверждение партнёром через /api/stores/{id}/inventory/confirm/
    - Погашение долга через /api/stores/{id}/pay-debt/
    - Отметка брака через /api/stores/{id}/inventory/report-defect/
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    # ✅ НОВОЕ v2.1: Запрет PUT/PATCH/DELETE
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self) -> QuerySet[StoreOrder]:
        """Получение заказов в зависимости от роли."""
        user = self.request.user

        if user.role == 'admin':
            return StoreOrder.objects.all().select_related(
                'store', 'partner', 'reviewed_by', 'confirmed_by'
            ).prefetch_related('items__product').order_by('-created_at')

        elif user.role == 'partner':
            # Партнёр видит только IN_TRANSIT (для информации)
            # Основная работа через stores/.../inventory/
            return StoreOrder.objects.filter(
                status=StoreOrderStatus.IN_TRANSIT
            ).select_related(
                'store', 'reviewed_by'
            ).prefetch_related('items__product').order_by('-created_at')

        elif user.role == 'store':
            # Магазин видит свои заказы
            store = StoreSelectionService.get_current_store(user)
            if store:
                return StoreOrder.objects.filter(
                    store=store
                ).select_related(
                    'partner', 'reviewed_by', 'confirmed_by'
                ).prefetch_related('items__product').order_by('-created_at')
            return StoreOrder.objects.none()

        return StoreOrder.objects.none()

    def get_serializer_class(self):
        """Выбор сериализатора."""
        if self.action == 'list':
            return StoreOrderListSerializer
        elif self.action == 'create':
            return StoreOrderCreateSerializer
        elif self.action == 'my_orders':
            return StoreOrderForStoreSerializer
        return StoreOrderDetailSerializer

    # =========================================================================
    # БАЗОВЫЕ ОПЕРАЦИИ
    # =========================================================================

    def list(self, request: Request) -> Response:
        """
        Список заказов с пагинацией.

        GET /api/orders/store-orders/
        GET /api/orders/store-orders/?status=pending
        GET /api/orders/store-orders/?status=in_transit
        """
        queryset = self.get_queryset()

        # Фильтрация по статусу
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Фильтрация по магазину (для админа)
        store_id = request.query_params.get('store_id')
        if store_id and request.user.role == 'admin':
            queryset = queryset.filter(store_id=store_id)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request: Request) -> Response:
        """
        Магазин создаёт заказ (ТЗ v2.0).

        POST /api/orders/store-orders/
        Body: {
            "items": [
                {"product_id": 1, "quantity": "10"},
                {"product_id": 2, "quantity": "2.5"}
            ]
        }

        ❗ НЕ ТРОГАТЬ! Основной endpoint создания заказа.
        """
        if request.user.role != 'store':
            return Response(
                {'error': 'Только магазины могут создавать заказы'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Проверка выбранного магазина
        store = StoreSelectionService.get_current_store(request.user)
        if not store:
            return Response(
                {'error': 'Выберите магазин для работы'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Преобразуем items в OrderItemData
        items_data = [
            OrderItemData(
                product_id=item['product_id'],
                quantity=item['quantity'],
                price=item.get('price'),
                is_bonus=item.get('is_bonus', False)
            )
            for item in serializer.validated_data['items']
        ]

        # Создаём заказ
        order = OrderWorkflowService.create_store_order(
            store=store,
            items_data=items_data,
            created_by=request.user,
            idempotency_key=serializer.validated_data.get('idempotency_key')
        )

        output = StoreOrderDetailSerializer(order)
        return Response(output.data, status=status.HTTP_201_CREATED)

    def retrieve(self, request: Request, pk=None) -> Response:
        """
        Детали заказа.

        GET /api/orders/store-orders/{id}/
        """
        order = self.get_object()
        serializer = StoreOrderDetailSerializer(order)
        return Response(serializer.data)

    # =========================================================================
    # ACTIONS ДЛЯ МАГАЗИНА
    # =========================================================================

    @action(
        detail=False,
        methods=['get'],
        url_path='my-orders',
        permission_classes=[IsAuthenticated, IsStore]
    )
    def my_orders(self, request: Request) -> Response:
        """
        Заказы текущего магазина (ТЗ v2.0).

        GET /api/orders/store-orders/my-orders/
        GET /api/orders/store-orders/my-orders/?status=pending
        GET /api/orders/store-orders/my-orders/?status=accepted
        GET /api/orders/store-orders/my-orders/?start_date=2024-01-01&end_date=2024-12-31

        Возвращает все заказы текущего магазина с полным содержимым.
        """
        store = StoreSelectionService.get_current_store(request.user)
        if not store:
            return Response(
                {'error': 'Выберите магазин для работы'},
                status=status.HTTP_400_BAD_REQUEST
            )

        orders = StoreOrder.objects.filter(
            store=store
        ).select_related('partner').prefetch_related('items__product').order_by('-created_at')

        # Фильтрация по статусу
        status_filter = request.query_params.get('status')
        if status_filter:
            orders = orders.filter(status=status_filter)

        # Фильтрация по датам
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if start_date:
            orders = orders.filter(created_at__date__gte=start_date)
        if end_date:
            orders = orders.filter(created_at__date__lte=end_date)

        # Пагинация
        page = self.paginate_queryset(orders)
        if page is not None:
            serializer = StoreOrderForStoreSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreOrderForStoreSerializer(orders, many=True)
        return Response(serializer.data)

    # =========================================================================
    # ACTIONS ДЛЯ АДМИНА
    # =========================================================================

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAuthenticated, IsAdmin]
    )
    def approve(self, request: Request, pk=None) -> Response:
        """
        Админ одобряет заказ.

        POST /api/orders/store-orders/{id}/approve/
        Body: {"assign_to_partner_id": 1}  // опционально

        После одобрения:
        - Статус: PENDING → IN_TRANSIT
        - Товары добавляются в инвентарь магазина
        - Партнёр видит заказ (если назначен)
        """
        order = self.get_object()

        # ✅ НОВОЕ v2.1: Проверка статуса
        if order.status != StoreOrderStatus.PENDING:
            return Response(
                {
                    'error': f'Невозможно одобрить заказ в статусе "{order.get_status_display()}"',
                    'current_status': order.status,
                    'required_status': StoreOrderStatus.PENDING
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = OrderApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        partner = None
        if serializer.validated_data.get('assign_to_partner_id'):
            from users.models import User
            try:
                partner = User.objects.get(
                    pk=serializer.validated_data['assign_to_partner_id'],
                    role='partner'
                )
            except User.DoesNotExist:
                return Response(
                    {'error': 'Партнёр не найден'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        order = OrderWorkflowService.admin_approve_order(
            order=order,
            admin_user=request.user,
            assign_to_partner=partner
        )

        output = StoreOrderDetailSerializer(order)
        return Response(output.data)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAuthenticated, IsAdmin]
    )
    def reject(self, request: Request, pk=None) -> Response:
        """
        Админ отклоняет заказ.

        POST /api/orders/store-orders/{id}/reject/
        Body: {"reason": "Товар закончился"}

        После отклонения:
        - Статус: PENDING → REJECTED
        - Товары НЕ добавляются в инвентарь
        """
        order = self.get_object()

        # ✅ НОВОЕ v2.1: Проверка статуса
        if order.status != StoreOrderStatus.PENDING:
            return Response(
                {
                    'error': f'Невозможно отклонить заказ в статусе "{order.get_status_display()}"',
                    'current_status': order.status,
                    'required_status': StoreOrderStatus.PENDING
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = OrderRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = OrderWorkflowService.admin_reject_order(
            order=order,
            admin_user=request.user,
            reason=serializer.validated_data['reason']
        )

        output = StoreOrderDetailSerializer(order)
        return Response(output.data)

# =============================================================================
# УДАЛЁННЫЕ VIEWSETS (v2.1)
# =============================================================================
#
# DefectiveProductViewSet - УДАЛЁН
# Причина: Брак теперь отмечается через stores:
#   POST /api/stores/{id}/inventory/report-defect/
#
# =============================================================================