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


    # Выбрать магазин
    path('select/', views.SelectStoreView.as_view(), name='select-store'),

    # Отменить выбор
    path('deselect/', views.DeselectStoreView.as_view(), name='deselect-store'),


    # Профиль текущего магазина (алиас для current)
    path('profile/', views.get_current_store_profile, name='store-profile'),

    # === ДОПОЛНИТЕЛЬНЫЕ ENDPOINTS ===

    # Пользователи в магазине
    path('stores/<int:pk>/users/', views.get_users_in_store, name='store-users'),
]