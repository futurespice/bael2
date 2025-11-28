# apps/orders/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StoreOrderViewSet, OrderReturnViewSet, PartnerOrderViewSet, OrderHistoryViewSet

router = DefaultRouter()
router.register(r'partner-orders', PartnerOrderViewSet, basename='partner-order')
router.register(r'store-orders', StoreOrderViewSet, basename='store-order')
router.register(r'order-returns', OrderReturnViewSet, basename='order-return')
router.register(r'order-history', OrderHistoryViewSet, basename='order-history')

urlpatterns = [
    path('', include(router.urls)),
]