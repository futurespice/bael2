# apps/reports/urls.py
"""URL маршруты для reports."""

from django.urls import path, include
from . import views
from rest_framework.routers import DefaultRouter
app_name = 'reports'


router = DefaultRouter()

router.register(r'partners/statistics',views.PartnerStatisticsViewSet, basename='partner-statistics')
router.register(r'partners/profile',views.PartnerProfileViewSet,basename='partner-profile')
router.register( r'partners/tracker',views.PartnerTrackerViewSet,basename='partner-tracker')

urlpatterns = [
    path('', include(router.urls)),
    # Статистика с круговой диаграммой
    path('statistics/', views.get_statistics, name='statistics'),

    # История магазина
    path('store-history/<int:store_id>/', views.get_store_history, name='store-history'),

    # Админ: статистика конкретного партнёра
    path(
        'admin/partner-statistics/<int:pk>/',
        views.AdminPartnerStatisticsViewSet.as_view({'get': 'retrieve'}),
        name='admin-partner-statistics'
    ),

]