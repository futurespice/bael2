# apps/orders/filters.py

import django_filters

from .models import OrderReturn, PartnerOrder, StoreOrder


class PartnerOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name="status")
    partner = django_filters.NumberFilter(field_name="partner_id")
    created_from = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_to = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte"
    )

    class Meta:
        model = PartnerOrder
        fields = ("status", "partner")


class StoreOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name="status")
    store = django_filters.NumberFilter(field_name="store_id")
    partner = django_filters.NumberFilter(field_name="partner_id")
    created_from = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_to = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte"
    )

    class Meta:
        model = StoreOrder
        fields = ("status", "store", "partner")


class OrderReturnFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name="status")
    store = django_filters.NumberFilter(field_name="store_id")
    partner = django_filters.NumberFilter(field_name="partner_id")
    created_from = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_to = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte"
    )

    class Meta:
        model = OrderReturn
        fields = ("status", "store", "partner")
