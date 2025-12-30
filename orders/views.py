# apps/orders/views.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.2
"""
Views для orders согласно ТЗ v2.0 и дизайну.

ИЗМЕНЕНИЯ v2.2:
1. Добавлен endpoint GET /api/orders/store-orders/my-orders/{id}/
2. Обновлены сериализаторы для соответствия дизайну
3. Убраны лишние поля (partner/partner_name из списков)
4. Добавлены поля owner_name, store_phone, items_summary

API ENDPOINTS:
- GET /api/orders/store-orders/ - список заказов (админ)
- POST /api/orders/store-orders/ - создание заказа (магазин)
- GET /api/orders/store-orders/{id}/ - детали заказа (админ)
- GET /api/orders/store-orders/my-orders/ - список заказов магазина
- GET /api/orders/store-orders/my-orders/{id}/ - детали заказа магазина (НОВОЕ!)
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
    # Админ
    StoreOrderListSerializer,
    StoreOrderDetailSerializer,
    # Магазин
    StoreOrderForStoreListSerializer,
    StoreOrderDetailForStoreSerializer,
    # Создание
    StoreOrderCreateSerializer,
    # Actions
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
    - GET /api/orders/store-orders/ - список (админ)
    - POST /api/orders/store-orders/ - создание (магазин)
    - GET /api/orders/store-orders/{id}/ - детали (админ)
    - GET /api/orders/store-orders/my-orders/ - мои заказы (магазин)
    - GET /api/orders/store-orders/my-orders/{id}/ - детали моего заказа (магазин) [НОВОЕ!]
    - POST /api/orders/store-orders/{id}/approve/ - одобрить (админ)
    - POST /api/orders/store-orders/{id}/reject/ - отклонить (админ)
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    # Запрет PUT/PATCH/DELETE
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self) -> QuerySet[StoreOrder]:
        """Получение заказов в зависимости от роли."""
        user = self.request.user

        if user.role == 'admin':
            return StoreOrder.objects.all().select_related(
                'store', 'partner', 'reviewed_by', 'confirmed_by'
            ).prefetch_related('items__product__images').order_by('-created_at')

        elif user.role == 'partner':
            # Партнёр видит только IN_TRANSIT
            return StoreOrder.objects.filter(
                status=StoreOrderStatus.IN_TRANSIT
            ).select_related(
                'store', 'reviewed_by'
            ).prefetch_related('items__product__images').order_by('-created_at')

        elif user.role == 'store':
            # Магазин видит свои заказы
            store = StoreSelectionService.get_current_store(user)
            if store:
                return StoreOrder.objects.filter(
                    store=store
                ).select_related(
                    'store', 'partner', 'reviewed_by', 'confirmed_by'
                ).prefetch_related('items__product__images').order_by('-created_at')
            return StoreOrder.objects.none()

        return StoreOrder.objects.none()

    def get_serializer_class(self):
        """Выбор сериализатора в зависимости от action."""
        if self.action == 'list':
            return StoreOrderListSerializer
        elif self.action == 'create':
            return StoreOrderCreateSerializer
        elif self.action == 'my_orders':
            return StoreOrderForStoreListSerializer
        elif self.action == 'my_order_detail':
            return StoreOrderDetailForStoreSerializer
        return StoreOrderDetailSerializer

    # =========================================================================
    # БАЗОВЫЕ ОПЕРАЦИИ
    # =========================================================================

    def list(self, request: Request) -> Response:
        """
        Список заказов с пагинацией (для АДМИНА).

        GET /api/orders/store-orders/
        GET /api/orders/store-orders/?status=pending
        GET /api/orders/store-orders/?status=in_transit
        GET /api/orders/store-orders/?store_id=5

        Response по дизайну:
        {
            "id": 1,
            "store": 5,
            "store_name": "Магазин №1",
            "owner_name": "Эргешов Тынчтык",    // ФИО владельца
            "store_phone": "+996 999 888 777",  // Телефон магазина
            "status": "pending",
            "status_display": "В ожидании",
            "total_amount": "450.00",
            "items_summary": "Запрос на 900 шт 20кг",  // Сводка
            "piece_count": 900,
            "weight_total": "20",
            "items_count": 5,
            "created_at": "2024-05-28T10:00:00Z"
        }
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
        Детали заказа (для АДМИНА).

        GET /api/orders/store-orders/{id}/

        Response по дизайну:
        {
            "id": 1,
            "store": 5,
            "store_name": "Магазин №1",
            "store_inn": "12345678901234",
            "owner_name": "Сыдыков Тариэл Кнатбекович",
            "store_phone": "+996777999666",
            "store_address": "ул. Примерная, 123",
            "status": "pending",
            "status_display": "В ожидании",
            "items": [
                {
                    "id": 1,
                    "product": 10,
                    "product_name": "Пельмени Красные",
                    "is_weight_based": false,
                    "quantity": "1",
                    "quantity_display": "1 шт",
                    "price": "450.00",
                    "total": "450.00",
                    "is_bonus": false,
                    "bonus_percent": "0%"
                }
            ],
            "items_summary": "3 шт",
            "total_items_count": 3,
            "total_amount": "450.00",
            ...
        }
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
        Список заказов текущего магазина (ТЗ v2.0).

        GET /api/orders/store-orders/my-orders/
        GET /api/orders/store-orders/my-orders/?status=pending
        GET /api/orders/store-orders/my-orders/?status=accepted
        GET /api/orders/store-orders/my-orders/?start_date=2024-01-01&end_date=2024-12-31

        Response по дизайну:
        {
            "id": 1,
            "store": 5,
            "store_name": "Магазин №1",
            "owner_name": "Эргешов Тынчтык",
            "store_phone": "+996 999 888 777",
            "status": "pending",
            "status_display": "В ожидании",
            "total_amount": "450.00",
            "items_summary": "Запрос на 900 шт 20кг",
            "piece_count": 900,
            "weight_total": "20",
            "items_count": 5,
            "created_at": "2024-05-28T10:00:00Z"
        }
        """
        store = StoreSelectionService.get_current_store(request.user)
        if not store:
            return Response(
                {'error': 'Выберите магазин для работы'},
                status=status.HTTP_400_BAD_REQUEST
            )

        orders = StoreOrder.objects.filter(
            store=store
        ).select_related('store').prefetch_related('items__product__images').order_by('-created_at')

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
            serializer = StoreOrderForStoreListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreOrderForStoreListSerializer(orders, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=['get'],
        url_path='my-orders/(?P<order_id>[^/.]+)',
        permission_classes=[IsAuthenticated, IsStore]
    )
    def my_order_detail(self, request: Request, order_id=None) -> Response:
        """
        Детали заказа для магазина (НОВОЕ! v2.2).

        GET /api/orders/store-orders/my-orders/{id}/

        Response по дизайну (формат каталога товаров):
        {
            "id": 1,
            "store": 5,
            "store_name": "Магазин №1",
            "owner_name": "Эргешов Тынчтык",
            "store_phone": "+996 999 888 777",
            "status": "in_transit",
            "status_display": "В пути",
            "items": [
                {
                    "id": 1,
                    "product_id": 10,
                    "product_name": "Курица",
                    "product_image": "/media/products/chicken.jpg",
                    "is_weight_based": true,
                    "is_bonus_product": false,
                    "requested": "5 кг",          // Запрошено
                    "quantity": "5.000",
                    "price": "450.00",
                    "total": "2250.00",
                    "is_bonus_item": false
                },
                {
                    "id": 2,
                    "product_id": 15,
                    "product_name": "Зеленые Красные",
                    "product_image": "/media/products/green.jpg",
                    "is_weight_based": false,
                    "is_bonus_product": true,     // Звёздочка
                    "requested": "545 шт",        // Запрошено
                    "quantity": "545",
                    "price": "450.00",
                    "total": "245250.00",
                    "is_bonus_item": false
                }
            ],
            "items_summary": "545 шт 5 кг",
            "total_items_count": 546,
            "total_amount": "247500.00",
            ...
        }
        """
        store = StoreSelectionService.get_current_store(request.user)
        if not store:
            return Response(
                {'error': 'Выберите магазин для работы'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            order = StoreOrder.objects.select_related(
                'store'
            ).prefetch_related(
                'items__product__images'
            ).get(
                pk=order_id,
                store=store
            )
        except StoreOrder.DoesNotExist:
            return Response(
                {'error': 'Заказ не найден'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = StoreOrderDetailForStoreSerializer(order)
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

        # Проверка статуса
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
        Body: {"reason": "Товара нет в наличии"}

        После отклонения:
        - Статус: PENDING → REJECTED
        - Товары НЕ добавляются в инвентарь
        """
        order = self.get_object()

        # Проверка статуса
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
            reason=serializer.validated_data.get('reason', '')
        )

        output = StoreOrderDetailSerializer(order)
        return Response(output.data)

    # =========================================================================
    # УДАЛЕНИЕ ЗАКАЗА (опционально, по дизайну есть иконка корзины)
    # =========================================================================

    @action(
        detail=True,
        methods=['delete'],
        permission_classes=[IsAuthenticated, IsAdmin]
    )
    def delete_order(self, request: Request, pk=None) -> Response:
        """
        Админ удаляет заказ (только PENDING).

        DELETE /api/orders/store-orders/{id}/delete_order/

        По дизайну: иконка корзины с подтверждением
        "Вы уверены, что хотите удалить этот запрос? Это потом нельзя вернуть"
        """
        order = self.get_object()

        # Можно удалить только PENDING заказы
        if order.status != StoreOrderStatus.PENDING:
            return Response(
                {
                    'error': f'Невозможно удалить заказ в статусе "{order.get_status_display()}"',
                    'message': 'Удалить можно только заказы в статусе "В ожидании"'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        order_id = order.id
        store_name = order.store.name
        order.delete()

        return Response({
            'success': True,
            'message': f'Заказ #{order_id} от магазина "{store_name}" удалён'
        })