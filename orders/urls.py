# apps/orders/urls.py - ОЧИЩЕННАЯ ВЕРСИЯ v2.1
"""
URL маршруты для orders.

ИЗМЕНЕНИЯ v2.1:
- УДАЛЁН router для defects (брак через stores)

ENDPOINTS:
- /api/orders/store-orders/ - CRUD заказов магазинов
- /api/orders/store-orders/my-orders/ - заказы текущего магазина
- /api/orders/store-orders/{id}/approve/ - одобрение админом
- /api/orders/store-orders/{id}/reject/ - отклонение админом
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'orders'

router = DefaultRouter()

# Заказы магазинов (основной workflow)
router.register(r'store-orders', views.StoreOrderViewSet, basename='store-order')


urlpatterns = [
    path('', include(router.urls)),
]