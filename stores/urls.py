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
    # Router URLs
    path('', include(router.urls)),

    # === ВЫБОР МАГАЗИНА (для role='store') ===

    # Список доступных магазинов для выбора
    path('stores/available/', views.AvailableStoresView.as_view(), name='available-stores'),

    # Выбрать магазин
    path('stores/select/', views.SelectStoreView.as_view(), name='select-store'),

    # Отменить выбор
    path('stores/deselect/', views.DeselectStoreView.as_view(), name='deselect-store'),

    # Текущий выбранный магазин
    path('stores/current/', views.CurrentStoreView.as_view(), name='current-store'),

    # Профиль текущего магазина (алиас для current)
    path('stores/profile/', views.get_current_store_profile, name='store-profile'),

    # === ДОПОЛНИТЕЛЬНЫЕ ENDPOINTS ===

    # Пользователи в магазине
    path('stores/<int:pk>/users/', views.get_users_in_store, name='store-users'),
]