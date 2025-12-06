# apps/products/urls.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
URL маршруты для products.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. Добавлен partner-expenses (расходы партнёра)
2. Добавлен product-expense-relations (связь товар-расход)
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ExpenseViewSet,
    PartnerExpenseViewSet,
    ProductViewSet,
    ProductionBatchViewSet,
    ProductImageViewSet,
    ProductExpenseRelationViewSet,
)

app_name = 'products'

router = DefaultRouter()

# Расходы на производство (админ)
router.register(r'expenses', ExpenseViewSet, basename='expense')

# Расходы партнёра (НОВОЕ v2.0)
router.register(r'partner-expenses', PartnerExpenseViewSet, basename='partner-expense')

# Товары
router.register(r'products', ProductViewSet, basename='product')

# Производство
router.register(r'production-batches', ProductionBatchViewSet, basename='production-batch')

# Изображения
router.register(r'images', ProductImageViewSet, basename='product-image')

# Связь товар-расход (НОВОЕ v2.0)
router.register(
    r'product-expense-relations', 
    ProductExpenseRelationViewSet, 
    basename='product-expense-relation'
)

urlpatterns = [
    path('', include(router.urls)),
]
