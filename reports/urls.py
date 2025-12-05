# apps/reports/urls.py
"""URL маршруты для reports."""

from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # Статистика с круговой диаграммой
    path('statistics/', views.get_statistics, name='statistics'),

    # История магазина
    path('store-history/<int:store_id>/', views.get_store_history, name='store-history'),
]