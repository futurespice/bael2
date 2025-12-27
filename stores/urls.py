# apps/stores/urls.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
"""
URL маршруты для stores.

КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ:
1. ✅ Добавлены эндпоинты available и current
2. ✅ Правильный порядок URL patterns (specific перед generic)
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'stores'

# Router для ViewSets
router = DefaultRouter()
router.register(r'regions', views.RegionViewSet, basename='region')
router.register(r'cities', views.CityViewSet, basename='city')
router.register(r'stores', views.StoreViewSet, basename='store')

# URL patterns
urlpatterns = [
    # =========================================================================
    # ВАЖНО: Specific URLs ПЕРЕД router.urls!
    # =========================================================================

    # === ВЫБОР МАГАЗИНА (для role='store') ===

    # Выбрать магазин (POST /api/stores/select/)
    # Поддерживает: Body {"store_id": 1} И Query ?store_id=1
    path('select/', views.SelectStoreView.as_view(), name='select-store'),

    # Отменить выбор (POST /api/stores/deselect/)
    path('deselect/', views.DeselectStoreView.as_view(), name='deselect-store'),

    # =========================================================================
    # Router URLs (должен быть ПОСЛЕДНИМ!)
    # =========================================================================
    path('', include(router.urls)),
]