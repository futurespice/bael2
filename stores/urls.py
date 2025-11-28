# apps/stores/urls.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RegionViewSet, CityViewSet, StoreViewSet, StoreSelectionViewSet,
    StoreProductRequestViewSet, StoreRequestViewSet,
    StoreInventoryViewSet, PartnerInventoryViewSet, ReturnRequestViewSet,
    # Новый ViewSet для профиля
    StoreProfileViewSet
)

router = DefaultRouter()

# География
router.register(r'regions', RegionViewSet, basename='regions')
router.register(r'cities', CityViewSet, basename='cities')

# Магазины (CRUD для админа)
router.register(r'stores', StoreViewSet, basename='stores')

# Выбор магазина (для роли STORE)
router.register(r'selection', StoreSelectionViewSet, basename='store-selection')

# Wishlist (Legacy - рекомендуется использовать /profile/wishlist/)
router.register(r'product-requests', StoreProductRequestViewSet, basename='product-requests')

# История запросов
router.register(r'requests', StoreRequestViewSet, basename='store-requests')

# Инвентарь
router.register(r'inventory', StoreInventoryViewSet, basename='store-inventory')
router.register(r'partner-inventory', PartnerInventoryViewSet, basename='partner-inventory')

# Возвраты
router.register(r'returns', ReturnRequestViewSet, basename='return-requests')

# === ПРОФИЛЬ МАГАЗИНА (главный endpoint для роли STORE) ===
# Регистрируем как singleton (без pk в URL)
# GET/PUT/PATCH /stores/profile/
# GET /stores/profile/debt/
# GET /stores/profile/statistics/
# GET /stores/profile/wishlist/
# POST /stores/profile/wishlist/add/
# DELETE /stores/profile/wishlist/remove/
# DELETE /stores/profile/wishlist/clear/
# POST /stores/profile/wishlist/submit/

urlpatterns = [
    # Профиль магазина (singleton endpoints)
    path('profile/', StoreProfileViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update'
    }), name='store-profile'),
    path('profile/debt/', StoreProfileViewSet.as_view({
        'get': 'debt'
    }), name='store-profile-debt'),
    path('profile/statistics/', StoreProfileViewSet.as_view({
        'get': 'statistics'
    }), name='store-profile-statistics'),
    path('profile/wishlist/', StoreProfileViewSet.as_view({
        'get': 'wishlist'
    }), name='store-profile-wishlist'),
    path('profile/wishlist/add/', StoreProfileViewSet.as_view({
        'post': 'wishlist_add'
    }), name='store-profile-wishlist-add'),
    path('profile/wishlist/remove/', StoreProfileViewSet.as_view({
        'delete': 'wishlist_remove'
    }), name='store-profile-wishlist-remove'),
    path('profile/wishlist/clear/', StoreProfileViewSet.as_view({
        'delete': 'wishlist_clear'
    }), name='store-profile-wishlist-clear'),
    path('profile/wishlist/submit/', StoreProfileViewSet.as_view({
        'post': 'wishlist_submit'
    }), name='store-profile-wishlist-submit'),

    # Router URLs
    path('', include(router.urls)),
]
