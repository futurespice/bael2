# apps/products/urls.py
"""URL маршруты для products."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ExpenseViewSet,
    ProductViewSet,
    ProductionBatchViewSet,
    ProductImageViewSet
)

app_name = 'products'

router = DefaultRouter()
router.register(r'expenses', ExpenseViewSet, basename='expense')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'production-batches', ProductionBatchViewSet, basename='production-batch')
router.register(r'images', ProductImageViewSet, basename='product-image')

urlpatterns = [
    path('', include(router.urls)),
]