# apps/orders/views.py

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from .filters import OrderReturnFilter, PartnerOrderFilter, StoreOrderFilter
from .models import (
    OrderHistory,
    OrderReturn,
    PartnerOrder,
    StoreOrder,
)
from .permissions import IsAdminOrPartner
from .serializers import (
    OrderHistorySerializer,
    OrderReturnSerializer,
    PartnerOrderSerializer,
    StoreOrderSerializer,
    DebtPaymentSerializer
)
from .services import OrderService
from decimal import Decimal

class PartnerOrderViewSet(viewsets.ModelViewSet):
    """
    Заказы партнёров.

    - admin видит все
    - partner — только свои
    """

    queryset = PartnerOrder.objects.all().select_related("partner")
    serializer_class = PartnerOrderSerializer
    filterset_class = PartnerOrderFilter
    permission_classes = [IsAdminOrPartner]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()
        if getattr(user, "role", None) == "admin" or user.is_superuser:
            return qs
        if getattr(user, "role", None) == "partner":
            return qs.filter(partner=user)
        return qs.none()


class StoreOrderViewSet(viewsets.ModelViewSet):
    queryset = StoreOrder.objects.select_related('store', 'partner', 'store_request').prefetch_related('items__product')
    serializer_class = StoreOrderSerializer
    filterset_class = StoreOrderFilter
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role == 'admin' or user.is_superuser:
            return qs
        if user.role == 'partner':
            return qs.filter(partner=user)
        if user.role == 'store':
            from stores.models import StoreSelection
            store_ids = StoreSelection.objects.filter(user=user).values_list('store_id', flat=True)
            return qs.filter(store_id__in=store_ids)
        return qs.none()

    @action(detail=True, methods=['post'], url_path='pay-debt')
    @transaction.atomic
    def pay_debt(self, request, pk=None):
        order = self.get_object()
        amount = Decimal(str(request.data.get('amount', '0')))
        comment = request.data.get('comment', '')

        payment = order.pay_debt(amount=amount, paid_by=request.user, comment=comment)
        return Response({
            'payment_id': payment.id,
            'remaining_debt': str(order.outstanding_debt)
        })

    @action(detail=True, methods=['get'], url_path='payment-history')
    def payment_history(self, request, pk=None):
        order = self.get_object()
        payments = order.debt_payments.all()
        serializer = DebtPaymentSerializer(payments, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='from-request')
    @transaction.atomic
    def create_from_request(self, request):
        store_request_id = request.data.get('store_request_id')
        paid_amount = Decimal(str(request.data.get('paid_amount', '0')))

        from stores.models import StoreRequest
        store_request = StoreRequest.objects.select_for_update().get(id=store_request_id)

        order = OrderService.create_store_order(
            store=store_request.store,
            partner=request.user,
            items_data=store_request.items.values('product', 'quantity', 'price'),
            store_request=store_request,
            paid_amount=paid_amount
        )

        return Response(StoreOrderSerializer(order).data, status=201)


class OrderReturnViewSet(viewsets.ModelViewSet):
    queryset = OrderReturn.objects.select_related('store', 'partner', 'order').prefetch_related('items')
    serializer_class = OrderReturnSerializer
    filterset_class = OrderReturnFilter
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'], url_path='change-status')
    @transaction.atomic
    def change_status(self, request, pk=None):
        order_return = self.get_object()
        new_status = request.data.get('status')
        comment = request.data.get('comment', '')

        if not new_status:
            return Response({'detail': 'status обязателен'}, status=400)

        updated = OrderService.change_order_return_status(
            order_return=order_return,
            new_status=new_status,
            changed_by=request.user,
            comment=comment
        )
        return Response(OrderReturnSerializer(updated).data)


class OrderHistoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Только чтение истории заказов.
    """

    queryset = OrderHistory.objects.all().select_related("changed_by", "product")
    serializer_class = OrderHistorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()
        role = getattr(user, "role", None)
        if role == "admin" or user.is_superuser:
            return qs
        # для партнёра/магазина можно фильтровать по связям, но тут оставляем общий read
        return qs
