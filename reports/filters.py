# apps/reports/filters.py

import django_filters

from .models import Report


class ReportFilter(django_filters.FilterSet):
    """Фильтр отчётов по типу, датам и автору."""

    type = django_filters.CharFilter(field_name="type")
    generated_by = django_filters.NumberFilter(field_name="generated_by_id")

    date_from = django_filters.DateFilter(field_name="date_from", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="date_to", lookup_expr="lte")

    created_from = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_to = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte"
    )

    class Meta:
        model = Report
        fields = ["type", "generated_by", "date_from", "date_to"]
