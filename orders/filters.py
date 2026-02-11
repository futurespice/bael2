# apps/orders/filters.py - ОЧИЩЕННАЯ ВЕРСИЯ v2.1
"""
Фильтры для orders.

ИЗМЕНЕНИЯ v2.1:
- УДАЛЁН PartnerOrderFilter (модель PartnerOrder удалена)
- УДАЛЁН OrderReturnFilter (модели OrderReturn не существует)
"""

import django_filters
from django_filters import filters
from .models import StoreOrder, ReturnedItem
from datetime import datetime, time
from django.utils import timezone


class StoreOrderFilter(django_filters.FilterSet):
    """
    Фильтр для заказов магазинов.

    Параметры:
    - status: статус заказа (pending, in_transit, accepted, rejected)
    - store: ID магазина
    - partner: ID партнёра
    - created_from: дата создания от (YYYY-MM-DD)
    - created_to: дата создания до (YYYY-MM-DD)
    """

    status = django_filters.CharFilter(field_name="status")
    store = django_filters.NumberFilter(field_name="store_id")
    partner = django_filters.NumberFilter(field_name="partner_id")
    created_from = django_filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="gte"
    )
    created_to = django_filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="lte"
    )

    class Meta:
        model = StoreOrder
        fields = ("status", "store", "partner")

# =============================================================================
# УДАЛЁННЫЕ ФИЛЬТРЫ (v2.1)
# =============================================================================
#
# PartnerOrderFilter - УДАЛЁН
# Причина: Модель PartnerOrder удалена (партнёры не делают заказы у админа по ТЗ v2.0)
#
# OrderReturnFilter - УДАЛЁН
# Причина: Модели OrderReturn не существует (мёртвый код)
#
# =============================================================================

class ReturnedItemFilter(django_filters.FilterSet):
    """Фильтры для возвращённых товаров."""

    order = django_filters.NumberFilter(field_name='order__id')
    store = django_filters.NumberFilter(field_name='order__store__id')
    store_id = django_filters.NumberFilter(field_name='order__store__id')  # Alias for frontend
    product = django_filters.NumberFilter(field_name='product__id')
    returned_by = django_filters.NumberFilter(field_name='returned_by__id')

    # Date filters (using methods for robust datetime filtering)
    date_from = django_filters.DateFilter(method='filter_start_date')
    start_date = django_filters.DateFilter(method='filter_start_date')
    date_to = django_filters.DateFilter(method='filter_end_date')
    end_date = django_filters.DateFilter(method='filter_end_date')

    class Meta:
        model = ReturnedItem
        fields = ['order', 'store', 'product', 'returned_by']

    def filter_start_date(self, queryset, name, value):
        if not value:
            return queryset
        # Начало дня
        start_of_day = datetime.combine(value, time.min)
        
        # Делаем aware, если включены таймзоны
        if timezone.is_aware(timezone.now()):
            current_timezone = timezone.get_current_timezone()
            start_of_day = timezone.make_aware(start_of_day, current_timezone)
            
        return queryset.filter(returned_at__gte=start_of_day)

    def filter_end_date(self, queryset, name, value):
        if not value:
            return queryset
        # Конец дня
        end_of_day = datetime.combine(value, time.max)
        
        # Делаем aware
        if timezone.is_aware(timezone.now()):
            current_timezone = timezone.get_current_timezone()
            end_of_day = timezone.make_aware(end_of_day, current_timezone)
            
        return queryset.filter(returned_at__lte=end_of_day)