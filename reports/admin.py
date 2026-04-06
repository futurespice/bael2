# apps/reports/admin.py
"""Django Admin для reports."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import DailyReport


class ReportTypeFilter(admin.SimpleListFilter):
    """Фильтр по типу записи: магазин или сводка."""
    title = _('Тип записи')
    parameter_name = 'report_type'

    def lookups(self, request, model_admin):
        return [
            ('store', 'По магазину'),
            ('summary', 'Сводка за день'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'store':
            return queryset.filter(store__isnull=False)
        if self.value() == 'summary':
            return queryset.filter(store__isnull=True)
        return queryset


@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = [
        'date', 'report_type_display', 'store', 'partner', 'region', 'city',
        'income', 'debt', 'paid_debt', 'defect_amount', 'expenses',
        'total_balance'
    ]
    list_filter = [ReportTypeFilter, 'date', 'partner', 'region', 'city']
    search_fields = ['store__name', 'store__inn', 'partner__email', 'partner__phone']
    readonly_fields = ['total_balance', 'profit', 'created_at', 'updated_at']

    def report_type_display(self, obj):
        return 'Сводка' if obj.store is None else 'Магазин'
    report_type_display.short_description = 'Тип'

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