# apps/products/urls.py
"""
URL-маршруты для модуля products.

Endpoint'ы:
- /api/products/expenses/ — CRUD расходов
- /api/products/products/ — CRUD товаров
- /api/products/recipes/ — CRUD рецептов
- /api/products/production/ — Записи производства
- /api/products/bonuses/ — История бонусов
- /api/products/counters/ — Счётчики товаров
- /api/products/defects/ — Бракованные товары
- /api/products/cost-snapshots/ — Кеш себестоимости
- /api/products/accounting/dynamic/ — Экран "Динамичный учёт"
- /api/products/accounting/static/ — Экран "Статичный учёт"
- /api/products/accounting/cost-table/ — Таблица себестоимости
- /api/products/production-finance/ — Финансовая сводка
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ExpenseViewSet,
    ProductViewSet,
    RecipeViewSet,
    ProductionRecordViewSet,
    BonusViewSet,
    StoreProductCounterViewSet,
    DefectiveProductViewSet,
    CostSnapshotViewSet,
    AccountingDynamicView,
    AccountingStaticView,
    CostTableView,
    ProductionFinanceView,
)

app_name = 'products'

router = DefaultRouter()

# CRUD ViewSets
router.register('expenses', ExpenseViewSet, basename='expense')
router.register('products', ProductViewSet, basename='product')
router.register('recipes', RecipeViewSet, basename='recipe')
router.register('production', ProductionRecordViewSet, basename='production')
router.register('bonuses', BonusViewSet, basename='bonus')
router.register('counters', StoreProductCounterViewSet, basename='counter')
router.register('defects', DefectiveProductViewSet, basename='defect')
router.register('cost-snapshots', CostSnapshotViewSet, basename='cost-snapshot')

urlpatterns = [
    # Router URLs
    path('', include(router.urls)),

    # Accounting endpoints (Динамичный / Статичный учёт)
    path(
        'accounting/dynamic/', AccountingDynamicView.as_view(), name='accounting-dynamic'
    ),
    path(
        'accounting/static/',
        AccountingStaticView.as_view(),
        name='accounting-static'
    ),
    path(
        'accounting/cost-table/',
        CostTableView.as_view(),
        name='cost-table'
    ),

    # Finance endpoint
    path(
        'production-finance/',
        ProductionFinanceView.as_view(),
        name='production-finance'
    ),
]
