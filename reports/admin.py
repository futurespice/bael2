# apps/reports/admin.py
"""Django Admin для reports."""

from django.contrib import admin
from .models import DailyReport


@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = [
        'date', 'store', 'partner', 'region', 'city',
        'income', 'debt', 'defect_amount', 'expenses',
        'total_balance'
    ]
    list_filter = ['date', 'region', 'city']
    search_fields = ['store__name', 'partner__email']
    readonly_fields = ['total_balance', 'profit', 'created_at', 'updated_at']

    fieldsets = [
        ('Фильтры', {
            'fields': ['date', 'store', 'partner', 'region', 'city']
        }),
        ('Финансы', {
            'fields': [
                'income', 'debt', 'paid_debt',
                'defect_amount', 'expenses',
                'total_balance', 'profit'
            ]
        }),
        ('Количество', {
            'fields': ['bonus_count', 'orders_count', 'products_sold_count']
        }),
        ('Системное', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]