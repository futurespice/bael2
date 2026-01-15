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
    """Сериализатор для статистики партнёра (10 показателей)."""

    period = serializers.CharField(help_text="Период: day, week, month, year")
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    # 1. Запрошено у админа
    requested_from_admin = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Запрошено товаров у админа: {total_amount, total_items}"
    )

    # 2. Продано магазинам
    sold_to_stores = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Продано магазинам: {total_amount, total_items}"
    )

    # 3. Остаток в инвентаре
    inventory_balance = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Остаток товара: {total_value, total_items}"
    )

    # 4. Расходы
    expenses = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Расходы: {total_amount, count}"
    )

    # 5. Брак
    defective = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Бракованные товары: {total_amount, total_items}"
    )

    # 6. Бонус
    bonus = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Бонусные товары: {total_count, total_value}"
    )

    # 7. Непогашенный долг
    unpaid_debt = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Непогашенный долг: {total_amount}"
    )

    # 8. Погашенный долг
    paid_debt = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Погашенный долг: {total_amount}"
    )

    # 9. Общая сумма (прибыль)
    total_profit = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Прибыль: {amount, formula}"
    )

    # 10. Итого
    summary = serializers.DictField(
        child=serializers.DecimalField(max_digits=14, decimal_places=2),
        help_text="Итоговые данные: {revenue, costs, net_profit}"
    )


class PartnerProfileSerializer(serializers.Serializer):
    """Сериализатор для профиля партнёра с историей продаж."""

    period = serializers.CharField()
    stores = serializers.ListField(
        child=serializers.DictField(),
        help_text="Список магазинов с заказами"
    )
    total_all_stores = serializers.DecimalField(max_digits=14, decimal_places=2)


class PartnerTrackerOrderSerializer(serializers.Serializer):
    """Упрощённый сериализатор для заказа в трекере."""

    id = serializers.IntegerField()
    store = serializers.DictField()
    order_type = serializers.CharField()
    status = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    debt_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    created_at = serializers.DateTimeField()
    accepted_at = serializers.DateTimeField(allow_null=True)
    items_count = serializers.IntegerField()
    returned_items_count = serializers.IntegerField()


class PartnerStoreSerializer(serializers.Serializer):
    """Сериализатор для магазина в списке партнёра."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    inn = serializers.CharField()
    total_debt = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_debt = serializers.DecimalField(max_digits=14, decimal_places=2)
    last_payment_date = serializers.DateTimeField(allow_null=True)
    orders_count = serializers.IntegerField()