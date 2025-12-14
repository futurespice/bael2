# apps/reports/serializers.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""Сериализаторы для reports."""

from datetime import date
from rest_framework import serializers
from .services import TimePeriod


class ReportFiltersSerializer(serializers.Serializer):
    """Сериализатор фильтров отчёта (ТЗ v2.0)."""

    period = serializers.ChoiceField(
        choices=[(p.value, p.value) for p in TimePeriod],
        default=TimePeriod.ALL_TIME.value,
        help_text='Период: day, week, month, half_year, year, all_time'
    )

    start_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text='Начальная дата (если нужен кастомный период)'
    )

    end_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text='Конечная дата'
    )

    store_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text='ID магазина для фильтрации'
    )

    partner_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text='ID партнёра для фильтрации'
    )

    region_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text='ID области для фильтрации'
    )

    city_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text='ID города для фильтрации'
    )


class StoreHistoryFiltersSerializer(serializers.Serializer):
    """
    Фильтры для истории магазина.

    ✅ ИСПРАВЛЕНО: start_date и end_date теперь опциональны
    """

    start_date = serializers.DateField(
        required=False,  # ✅ Теперь НЕ обязательно
        help_text='Начальная дата (YYYY-MM-DD). По умолчанию: дата первого заказа'
    )

    end_date = serializers.DateField(
        required=False,  # ✅ Теперь НЕ обязательно
        help_text='Конечная дата (YYYY-MM-DD). По умолчанию: сегодня'
    )


class StatisticsSerializer(serializers.Serializer):
    # Финансовые показатели
    income = serializers.DecimalField(max_digits=14, decimal_places=2)
    debt = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_debt = serializers.DecimalField(max_digits=14, decimal_places=2)
    defect_amount = serializers.DecimalField(max_digits=14, decimal_places=2)

    # ✅ НОВОЕ: Разделённые расходы
    partner_expenses = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text='Расходы партнёра (ручной ввод)'
    )
    production_expenses = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text='Себестоимость производства'
    )
    total_expenses = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text='Общая сумма расходов'
    )

    # Количественные
    bonus_count = serializers.IntegerField()
    orders_count = serializers.IntegerField()
    products_count = serializers.IntegerField()

    # Вычисляемые
    total_balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    profit = serializers.DecimalField(max_digits=14, decimal_places=2)