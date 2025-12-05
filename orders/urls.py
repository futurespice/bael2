# apps/orders/urls.py
"""URL маршруты для orders."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'orders'

router = DefaultRouter()
router.register(r'store-orders', views.StoreOrderViewSet, basename='store-order')
router.register(r'defects', views.DefectiveProductViewSet, basename='defect')

urlpatterns = [
    path('', include(router.urls)),
]