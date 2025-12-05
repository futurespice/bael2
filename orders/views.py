# apps/orders/views.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Views для orders согласно ТЗ v2.0.

API ENDPOINTS:
1. Заказы магазинов:
   - GET/POST /api/orders/store-orders/
   - GET /api/orders/store-orders/{id}/
   - POST /api/orders/store-orders/{id}/approve/ (админ)
   - POST /api/orders/store-orders/{id}/reject/ (админ)
   - POST /api/orders/store-orders/{id}/confirm/ (партнёр)
   - POST /api/orders/store-orders/{id}/cancel-items/ (магазин)

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
    OrderHistorySerializer,
)
from .services import (
    OrderWorkflowService,
    DebtService,
    DefectiveProductService,
    OrderItemData,
)
from .permissions import IsAdmin, IsPartner, IsStore


class StoreOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet для заказов магазинов (ТЗ v2.0).

    ДОСТУП:
    - Админ: все заказы
    - Партнёр: только IN_TRANSIT
    - Магазин: только свои заказы
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[StoreOrder]:
        """Получение заказов в зависимости от роли."""
        user = self.request.user

        if user.role == 'admin':
            return StoreOrder.objects.all()

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

    @action(detail=True, methods=['post'], permission_classes=[IsPartner])
    def confirm(self, request: Request, pk=None) -> Response:
        """
        Партнёр подтверждает заказ.

        POST /api/orders/store-orders/{id}/confirm/
        Body: {
            "prepayment_amount": "500",
            "items_to_remove": [1, 2]
        }
        """
        order = self.get_object()

        serializer = OrderConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = OrderWorkflowService.partner_confirm_order(
            order=order,
            partner_user=request.user,
            prepayment_amount=serializer.validated_data['prepayment_amount'],
            items_to_remove_from_inventory=serializer.validated_data.get('items_to_remove', [])
        )

        output = StoreOrderDetailSerializer(order)
        return Response(output.data)

    @action(detail=True, methods=['post'], permission_classes=[IsStore])
    def cancel_items(self, request: Request, pk=None) -> Response:
        """
        Магазин отменяет товары (только в статусе PENDING).

        POST /api/orders/store-orders/{id}/cancel-items/
        Body: {"item_ids": [1, 2, 3]}
        """
        order = self.get_object()

        item_ids = request.data.get('item_ids', [])
        if not item_ids:
            return Response(
                {'error': 'item_ids обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order = OrderWorkflowService.store_cancel_items(
            order=order,
            item_ids_to_cancel=item_ids,
            cancelled_by=request.user
        )

        output = StoreOrderDetailSerializer(order)
        return Response(output.data)

    @action(detail=True, methods=['post'])
    def pay_debt(self, request: Request, pk=None) -> Response:
        """
        Погашение долга по заказу.

        POST /api/orders/store-orders/{id}/pay-debt/
        Body: {"amount": "1000", "comment": "Оплата"}
        """
        order = self.get_object()

        serializer = PayDebtSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = DebtService.pay_order_debt(
            order=order,
            amount=serializer.validated_data['amount'],
            paid_by=request.user,
            received_by=order.partner,
            comment=serializer.validated_data.get('comment', '')
        )

        output = DebtPaymentSerializer(payment)
        return Response(output.data)

    @action(detail=True, methods=['post'], permission_classes=[IsStore])
    def report_defect(self, request: Request, pk=None) -> Response:
        """
        Магазин заявляет о браке.

        POST /api/orders/store-orders/{id}/report-defect/
        Body: {
            "product_id": 1,
            "quantity": "2",
            "price": "100",
            "reason": "Испорчено"
        }
        """
        order = self.get_object()

        serializer = ReportDefectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from products.models import Product
        product = Product.objects.get(pk=serializer.validated_data['product_id'])

        defect = DefectiveProductService.report_defect(
            order=order,
            product=product,
            quantity=serializer.validated_data['quantity'],
            price=serializer.validated_data['price'],
            reason=serializer.validated_data['reason'],
            reported_by=request.user
        )

        output = DefectiveProductSerializer(defect)
        return Response(output.data, status=status.HTTP_201_CREATED)


class DefectiveProductViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet для бракованных товаров."""

    queryset = DefectiveProduct.objects.all()
    serializer_class = DefectiveProductSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'], permission_classes=[IsPartner])
    def approve(self, request: Request, pk=None) -> Response:
        """
        Партнёр подтверждает брак.

        POST /api/orders/defects/{id}/approve/
        """
        defect = self.get_object()

        defect = DefectiveProductService.approve_defect(
            defect=defect,
            approved_by=request.user
        )

        serializer = self.get_serializer(defect)
        return Response(serializer.data)