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


# =============================================================================
# PARTNER STATISTICS (v3.0)
# =============================================================================

class PartnerStatisticsSerializer(serializers.Serializer):
    """Статистика партнера (10 показателей)."""
    
    requested_from_admin = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Сумма запрошенных товаров'
    )
    sold_to_stores = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Сумма проданных товаров'
    )
    inventory_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Стоимость товаров в инвентаре'
    )
    expenses = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Сумма расходов партнера'
    )
    defective = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Сумма бракованных товаров'
    )
    bonus = serializers.IntegerField(help_text='Количество бонусных товаров')
    unpaid_debt = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Непогашенный долг магазинов'
    )
    paid_debt = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Погашенный долг'
    )
    total_profit = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Прибыль: продано - расходы - брак'
    )
    grand_total = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text='Итоговый баланс'
    )
    period = serializers.CharField(help_text='Период статистики')
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)


class PartnerProfileSerializer(serializers.Serializer):
    """Профиль партнера."""
    
    date = serializers.DateField()
    store_name = serializers.CharField()
    store_inn = serializers.CharField()
    product = serializers.CharField()
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class PartnerTrackerSerializer(serializers.Serializer):
    """Трекер заказов партнера."""
    
    order_id = serializers.IntegerField()
    store_name = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    debt_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    created_at = serializers.DateTimeField()
    confirmed_at = serializers.DateTimeField(allow_null=True)