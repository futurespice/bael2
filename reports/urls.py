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
    
    # Partner Statistics (v3.0)
    path('partner-statistics/', views.partner_statistics, name='partner-statistics'),
    path('partner-profile/', views.partner_profile, name='partner-profile'),
    path('partner-tracker/', views.partner_tracker, name='partner-tracker'),
]