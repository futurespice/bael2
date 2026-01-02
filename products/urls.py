# apps/products/urls.py - ПОЛНАЯ ВЕРСИЯ v3.0
"""URL конфигурация для products."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ExpenseViewSet,
    ProductRecipeViewSet,
    ProductViewSet,
    ProductionBatchViewSet,
    ProductImageViewSet,
    PartnerExpenseViewSet,
    ProductExpenseRelationViewSet,
)

# Создаём роутер
router = DefaultRouter()

# Регистрируем ViewSets
router.register(r'expenses', ExpenseViewSet, basename='expense')
router.register(r'product-recipes', ProductRecipeViewSet, basename='product-recipe')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'production-batches', ProductionBatchViewSet, basename='production-batch')
router.register(r'product-images', ProductImageViewSet, basename='product-image')
router.register(r'partner-expenses', PartnerExpenseViewSet, basename='partner-expense')

# Обратная совместимость
router.register(r'product-expense-relations', ProductExpenseRelationViewSet, basename='product-expense-relation')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
]