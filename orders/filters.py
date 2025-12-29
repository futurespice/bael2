# apps/orders/filters.py - ОЧИЩЕННАЯ ВЕРСИЯ v2.1
"""
Фильтры для orders.

ИЗМЕНЕНИЯ v2.1:
- УДАЛЁН PartnerOrderFilter (модель PartnerOrder удалена)
- УДАЛЁН OrderReturnFilter (модели OrderReturn не существует)
"""

import django_filters

from .models import StoreOrder


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