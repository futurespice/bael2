# apps/orders/views.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Views для orders согласно ТЗ v2.0.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. УДАЛЁН cancel_items action (по требованию #10)
2. Добавлен my_orders action для магазина (требование #13)
3. Добавлена пагинация

API ENDPOINTS:
1. Заказы магазинов:
   - GET/POST /api/orders/store-orders/
   - GET /api/orders/store-orders/{id}/
   - GET /api/orders/store-orders/my-orders/ (магазин)
   - POST /api/orders/store-orders/{id}/approve/ (админ)
   - POST /api/orders/store-orders/{id}/reject/ (админ)
   - POST /api/orders/store-orders/{id}/confirm/ (партнёр)

2. Долги:
   - POST /api/orders/store-orders/{id}/pay-debt/
   - GET /api/orders/debts/store/{store_id}/

3. Брак:
   - POST /api/orders/store-orders/{id}/report-defect/
   - POST /api/orders/defects/{id}/approve/
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
from django.utils.timezone import timezone
from stores.models import Store
from stores.services import StoreSelectionService

from .models import (
    StoreOrder,
    StoreOrderStatus,
    DefectiveProduct,
)
from .serializers import (
    StoreOrderListSerializer,
    StoreOrderDetailSerializer,
    StoreOrderCreateSerializer,
    OrderApproveSerializer,
    OrderRejectSerializer,
    OrderConfirmSerializer,
    DebtPaymentSerializer,
    PayDebtSerializer,
    DefectiveProductSerializer,
    ReportDefectSerializer,
    OrderHistorySerializer, StoreOrderForStoreSerializer,
)
from .services import (
    OrderWorkflowService,
    DebtService,
    DefectiveProductService,
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
    - Админ: все заказы
    - Партнёр: только IN_TRANSIT
    - Магазин: только свои заказы

    ВАЖНО (ТЗ v2.0):
    - Магазин НЕ может отменять товары (cancel_items удалён)
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self) -> QuerySet[StoreOrder]:
        """Получение заказов в зависимости от роли."""
        user = self.request.user

        if user.role == 'admin':
            return StoreOrder.objects.all().select_related(
                'store', 'partner'
            ).prefetch_related('items__product')

        elif user.role == 'partner':
            # Партнёр видит только IN_TRANSIT
            return OrderWorkflowService.get_orders_for_partner(user)

        elif user.role == 'store':
            # Магазин видит свои заказы
            store = StoreSelectionService.get_current_store(user)
            if store:
                return OrderWorkflowService.get_store_orders(store)
            return StoreOrder.objects.none()

        return StoreOrder.objects.none()

    def get_serializer_class(self):
        """Выбор сериализатора."""
        if self.action == 'list':
            return StoreOrderListSerializer
        elif self.action == 'create':
            return StoreOrderCreateSerializer
        return StoreOrderDetailSerializer

    def list(self, request: Request) -> Response:
        """Список заказов с пагинацией."""
        queryset = self.get_queryset()
        
        # Фильтрация по статусу
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
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

    # =========================================================================
    # ACTIONS ДЛЯ МАГАЗИНА (ТЗ v2.0, требование #13)
    # =========================================================================

    @action(detail=False, methods=['get'], permission_classes=[IsStore])
    def my_orders(self, request: Request) -> Response:
        """
        Заказы магазина (ТЗ v2.0, требование #13).

        GET /api/orders/store-orders/my-orders/
        GET /api/orders/store-orders/my-orders/?status=pending
        GET /api/orders/store-orders/my-orders/?start_date=2024-01-01&end_date=2024-12-31
        
        Возвращает все заказы текущего магазина с фильтрацией.
        """
        store = StoreSelectionService.get_current_store(request.user)
        
        if not store:
            return Response(
                {'error': 'Выберите магазин для работы'},
                status=status.HTTP_400_BAD_REQUEST
            )

        orders = StoreOrder.objects.filter(store=store).select_related(
            'partner'
        ).prefetch_related('items__product')

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
            serializer = StoreOrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreOrderListSerializer(orders, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[IsStore])
    def order_history(self, request: Request) -> Response:
        """
        История заказов магазина.

        GET /api/orders/store-orders/order-history/
        """
        store = StoreSelectionService.get_current_store(request.user)
        
        if not store:
            return Response(
                {'error': 'Выберите магазин для работы'},
                status=status.HTTP_400_BAD_REQUEST
            )

        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED
        ).select_related('partner').prefetch_related('items__product')

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
            serializer = StoreOrderDetailSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreOrderDetailSerializer(orders, many=True)
        return Response(serializer.data)


    # =========================================================================
    # ACTIONS ДЛЯ АДМИНА
    # =========================================================================

    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def approve(self, request: Request, pk=None) -> Response:
        """
        Админ одобряет заказ.

        POST /api/orders/store-orders/{id}/approve/
        Body: {"assign_to_partner_id": 1}
        """
        order = self.get_object()

        serializer = OrderApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        partner = None
        if serializer.validated_data.get('assign_to_partner_id'):
            from users.models import User
            partner = User.objects.get(pk=serializer.validated_data['assign_to_partner_id'])

        order = OrderWorkflowService.admin_approve_order(
            order=order,
            admin_user=request.user,
            assign_to_partner=partner
        )

        output = StoreOrderDetailSerializer(order)
        return Response(output.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def reject(self, request: Request, pk=None) -> Response:
        """
        Админ отклоняет заказ.

        POST /api/orders/store-orders/{id}/reject/
        Body: {"reason": "Товар закончился"}
        """
        order = self.get_object()

        serializer = OrderRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = OrderWorkflowService.admin_reject_order(
            order=order,
            admin_user=request.user,
            reason=serializer.validated_data['reason']
        )

        output = StoreOrderDetailSerializer(order)
        return Response(output.data)

    # =========================================================================
    # ACTIONS ДЛЯ ПАРТНЁРА
    # =========================================================================

    # @action(detail=True, methods=['post'], permission_classes=[IsPartner])
    # def confirm(self, request: Request, pk=None) -> Response:
    #     """
    #     Партнёр подтверждает заказ.
    #
    #     POST /api/orders/store-orders/{id}/confirm/
    #     Body: {
    #         "prepayment_amount": "500",
    #         "items_to_remove": [1, 2]
    #     }
    #     """
    #     order = self.get_object()
    #
    #     serializer = OrderConfirmSerializer(data=request.data)
    #     serializer.is_valid(raise_exception=True)
    #
    #     order = OrderWorkflowService.partner_confirm_order(
    #         order=order,
    #         partner_user=request.user,
    #         prepayment_amount=serializer.validated_data['prepayment_amount'],
    #         items_to_remove_from_inventory=serializer.validated_data.get('items_to_remove', [])
    #     )
    #
    #     output = StoreOrderDetailSerializer(order)
    #     return Response(output.data)
    # @action(
    #     detail=True,
    #     methods=['post'],
    #     url_path='inventory/confirm',
    #     permission_classes=[IsPartner]
    # )
    # def confirm_inventory(self, request: Request, pk=None) -> Response:
    #     """
    #     Партнёр подтверждает ВЕСЬ инвентарь магазина одним действием (ТЗ v2.0).
    #
    #     POST /api/stores/{store_id}/inventory/confirm/
    #
    #     Body: {
    #         "prepayment_amount": 5000,          // Предоплата (может быть 0)
    #         "items_to_remove": [1, 3, 5]        // ID товаров для удаления (опционально)
    #     }
    #
    #     Workflow:
    #     1. Партнёр может удалить ненужные товары из инвентаря
    #     2. Указывает предоплату (0 по умолчанию, не больше суммы инвентаря)
    #     3. ВСЕ заказы магазина "В пути" → "Принят"
    #     4. Долг = сумма инвентаря - предоплата
    #     5. Магазин видит подтверждённый инвентарь
    #     """
    #     from decimal import Decimal
    #     from django.db.models import F, Sum
    #     from orders.models import (
    #         StoreOrder,
    #         StoreOrderStatus,
    #         OrderHistory,
    #         OrderType,
    #         StoreOrderItem
    #     )
    #     from stores.models import StoreInventory
    #     from stores.services import BonusCalculationService
    #
    #     store = self.get_object()
    #
    #     # Валидация партнёра
    #     if request.user.role != 'partner':
    #         return Response(
    #             {'error': 'Только партнёры могут подтверждать инвентарь'},
    #             status=status.HTTP_403_FORBIDDEN
    #         )
    #
    #     # Валидация данных
    #     prepayment_amount = Decimal(str(request.data.get('prepayment_amount', 0)))
    #     items_to_remove = request.data.get('items_to_remove', [])
    #
    #     if prepayment_amount < 0:
    #         return Response(
    #             {'error': 'Предоплата не может быть отрицательной'},
    #             status=status.HTTP_400_BAD_REQUEST
    #         )
    #
    #     # Получаем все заказы "В пути"
    #     in_transit_orders = StoreOrder.objects.filter(
    #         store=store,
    #         status=StoreOrderStatus.IN_TRANSIT
    #     ).prefetch_related('items__product')
    #
    #     if not in_transit_orders.exists():
    #         return Response(
    #             {'error': 'Нет заказов для подтверждения'},
    #             status=status.HTTP_400_BAD_REQUEST
    #         )
    #
    #     # Удаляем товары из инвентаря (если партнёр указал)
    #     if items_to_remove:
    #         # Удаляем из инвентаря
    #         StoreInventory.objects.filter(
    #             store=store,
    #             product_id__in=items_to_remove
    #         ).delete()
    #
    #         # Удаляем из всех заказов
    #         StoreOrderItem.objects.filter(
    #             order__in=in_transit_orders,
    #             product_id__in=items_to_remove
    #         ).delete()
    #
    #     # Пересчитываем суммы заказов после удаления товаров
    #     for order in in_transit_orders:
    #         order.recalc_total()
    #
    #     # Вычисляем общую сумму всех заказов
    #     total_amount_data = in_transit_orders.aggregate(
    #         total=Sum('total_amount')
    #     )
    #     total_inventory_amount = total_amount_data['total'] or Decimal('0')
    #
    #     if total_inventory_amount == 0:
    #         return Response(
    #             {'error': 'Инвентарь пуст после удаления товаров'},
    #             status=status.HTTP_400_BAD_REQUEST
    #         )
    #
    #     # Проверка предоплаты
    #     if prepayment_amount > total_inventory_amount:
    #         return Response(
    #             {
    #                 'error': f'Предоплата ({prepayment_amount} сом) не может превышать '
    #                          f'сумму инвентаря ({total_inventory_amount} сом)'
    #             },
    #             status=status.HTTP_400_BAD_REQUEST
    #         )
    #
    #     # Подтверждаем ВСЕ заказы
    #     confirmed_count = 0
    #     total_debt = Decimal('0')
    #
    #     # Распределяем предоплату пропорционально между заказами
    #     orders_list = list(in_transit_orders)
    #     remaining_prepayment = prepayment_amount
    #
    #     for idx, order in enumerate(orders_list):
    #         # Рассчитываем долю предоплаты для этого заказа
    #         if idx == len(orders_list) - 1:
    #             # Последний заказ получает остаток
    #             order_prepayment = remaining_prepayment
    #         else:
    #             # Пропорционально сумме заказа
    #             if total_inventory_amount > 0:
    #                 ratio = order.total_amount / total_inventory_amount
    #                 order_prepayment = (prepayment_amount * ratio).quantize(Decimal('0.01'))
    #             else:
    #                 order_prepayment = Decimal('0')
    #             remaining_prepayment -= order_prepayment
    #
    #         # Рассчитываем долг
    #         order_debt = order.total_amount - order_prepayment
    #
    #         # Обновляем заказ
    #         order.prepayment_amount = order_prepayment
    #         order.debt_amount = order_debt
    #         order.status = StoreOrderStatus.ACCEPTED
    #         order.partner = request.user
    #         order.confirmed_by = request.user
    #         order.confirmed_at = timezone.now()
    #         order.save()
    #
    #         total_debt += order_debt
    #         confirmed_count += 1
    #
    #         # История
    #         OrderHistory.objects.create(
    #             order_type=OrderType.STORE,
    #             order_id=order.id,
    #             old_status=StoreOrderStatus.IN_TRANSIT,
    #             new_status=StoreOrderStatus.ACCEPTED,
    #             changed_by=request.user,
    #             comment=(
    #                 f'Подтверждено партнёром через инвентарь. '
    #                 f'Сумма заказа: {order.total_amount} сом. '
    #                 f'Предоплата: {order_prepayment} сом. '
    #                 f'Долг: {order_debt} сом.'
    #             )
    #         )
    #
    #     # ✅ ИСПРАВЛЕНО: Обновляем долг магазина через update()
    #     Store.objects.filter(pk=store.pk).update(
    #         debt=F('debt') + total_debt
    #     )
    #     store.refresh_from_db()
    #
    #     # Получаем обновлённый инвентарь
    #     inventory = BonusCalculationService.get_inventory_with_bonuses(store)
    #
    #     return Response({
    #         'success': True,
    #         'message': f'Инвентарь подтверждён. Принято заказов: {confirmed_count}',
    #         'confirmed_orders_count': confirmed_count,
    #         'total_inventory_amount': float(total_inventory_amount),
    #         'prepayment_amount': float(prepayment_amount),
    #         'total_debt_created': float(total_debt),
    #         'store_total_debt': float(store.debt),
    #         'inventory': inventory
    #     })
    # # =========================================================================
    # # ОБЩИЕ ACTIONS
    # # =========================================================================
    #
    # @action(detail=True, methods=['post'])
    # def pay_debt(self, request: Request, pk=None) -> Response:
    #     """
    #     Погашение долга по заказу.
    #
    #     POST /api/orders/store-orders/{id}/pay-debt/
    #     Body: {"amount": "1000", "comment": "Оплата"}
    #     """
    #     order = self.get_object()
    #
    #     serializer = PayDebtSerializer(data=request.data)
    #     serializer.is_valid(raise_exception=True)
    #
    #     payment = DebtService.pay_order_debt(
    #         order=order,
    #         amount=serializer.validated_data['amount'],
    #         paid_by=request.user,
    #         received_by=order.partner,
    #         comment=serializer.validated_data.get('comment', '')
    #     )
    #
    #     output = DebtPaymentSerializer(payment)
    #     return Response(output.data)


    @action(
        detail=False,
        methods=['get'],
        url_path='my-orders',
        permission_classes=[IsAuthenticated, IsStore]
    )
    def my_orders(self, request: Request) -> Response:
        """
        Все заказы магазина с полным содержимым.

        КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ:
        - ✅ Включает поле 'items' с товарами
        - ✅ Оптимизирован с prefetch_related
        - ✅ Фильтрация по статусу и датам
        - ✅ Пагинация

        GET /api/orders/store-orders/my-orders/
        GET /api/orders/store-orders/my-orders/?status=pending
        GET /api/orders/store-orders/my-orders/?start_date=2024-01-01&end_date=2024-12-31

        Query Parameters:
        - status: Фильтр по статусу (pending, in_transit, accepted, rejected)
        - start_date: Начальная дата (YYYY-MM-DD)
        - end_date: Конечная дата (YYYY-MM-DD)
        - page: Номер страницы (по умолчанию 1)
        - page_size: Размер страницы (по умолчанию 20)

        Response:
            {
                "count": 25,
                "next": "http://.../my-orders/?page=2",
                "previous": null,
                "results": [
                    {
                        "id": 1,
                        "items": [  // ✅ КРИТИЧЕСКИ ВАЖНО!
                            {
                                "product_name": "Манты",
                                "quantity": "2.500",
                                "price": "200.00",
                                ...
                            }
                        ],
                        ...
                    }
                ]
            }

        Статус коды:
        - 200: Успешно
        - 400: Магазин не выбран
        - 403: Недостаточно прав
        """
        # Проверка выбранного магазина
        store = StoreSelectionService.get_current_store(request.user)

        if not store:
            return Response(
                {
                    'error': 'Магазин не выбран',
                    'detail': 'Пожалуйста, выберите магазин для просмотра заказов',
                    'action': 'POST /api/stores/select/ {"store_id": <id>}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ КРИТИЧЕСКИ ВАЖНО: prefetch_related для избежания N+1 запросов
        orders = StoreOrder.objects.filter(
            store=store
        ).select_related(
            'partner'  # Оптимизация для партнёра
        ).prefetch_related(
            'items__product'  # ✅ КРИТИЧЕСКИ ВАЖНО: Загружаем товары вместе с заказами!
        ).order_by('-created_at')

        # Фильтрация по статусу
        status_filter = request.query_params.get('status')
        if status_filter:
            # Валидация статуса
            valid_statuses = [choice[0] for choice in StoreOrderStatus.choices]
            if status_filter not in valid_statuses:
                return Response(
                    {
                        'error': 'Неверный статус',
                        'detail': f'Допустимые значения: {", ".join(valid_statuses)}'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
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
            # ✅ ИСПРАВЛЕНО: Используем новый сериализатор с items
            serializer = StoreOrderForStoreSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        # Если пагинация отключена
        serializer = StoreOrderForStoreSerializer(orders, many=True)
        return Response(serializer.data)

    # =============================================================================
    # ДОПОЛНИТЕЛЬНО: Быстрые фильтры по статусам
    # =============================================================================

    @action(
        detail=False,
        methods=['get'],
        url_path='pending',
        permission_classes=[IsAuthenticated, IsStore]
    )
    def pending(self, request: Request) -> Response:
        """
        Заказы в ожидании (быстрый фильтр).

        GET /api/orders/store-orders/pending/
        """
        store = StoreSelectionService.get_current_store(request.user)

        if not store:
            return Response(
                {'error': 'Выберите магазин'},
                status=status.HTTP_400_BAD_REQUEST
            )

        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.PENDING
        ).select_related('partner').prefetch_related('items__product')

        page = self.paginate_queryset(orders)
        if page:
            serializer = StoreOrderForStoreSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreOrderForStoreSerializer(orders, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=['get'],
        url_path='in-transit',
        permission_classes=[IsAuthenticated, IsStore]
    )
    def in_transit(self, request: Request) -> Response:
        """Заказы в пути."""
        store = StoreSelectionService.get_current_store(request.user)
        if not store:
            return Response({'error': 'Выберите магазин'}, status=400)

        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).select_related('partner').prefetch_related('items__product')

        page = self.paginate_queryset(orders)
        if page:
            serializer = StoreOrderForStoreSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreOrderForStoreSerializer(orders, many=True)
        return Response(serializer.data)

class DefectiveProductViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet для бракованных товаров."""

    queryset = DefectiveProduct.objects.all().select_related(
        'order__store', 'product'
    )
    serializer_class = DefectiveProductSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    # @action(detail=True, methods=['post'], permission_classes=[IsPartner])
    # def approve(self, request: Request, pk=None) -> Response:
    #     """
    #     Партнёр подтверждает брак.
    #
    #     POST /api/orders/defects/{id}/approve/
    #     """
    #     defect = self.get_object()
    #
    #     defect = DefectiveProductService.approve_defect(
    #         defect=defect,
    #         approved_by=request.user
    #     )
    #
    #     serializer = self.get_serializer(defect)
    #     return Response(serializer.data)
