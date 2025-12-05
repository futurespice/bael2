# apps/reports/services.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Сервисы для статистики и отчётов согласно ТЗ v2.0.

ОСНОВНОЙ СЕРВИС:
- ReportService: Генерация статистики в реальном времени

ТЗ v2.0 ТРЕБОВАНИЯ:
- Круговые диаграммы (доход, долг, брак, расходы)
- Календарная фильтрация (день, неделя, месяц, полгода, год, всё время)
- Фильтрация по магазинам, городам, областям
- Общий баланс: доход - брак - расходы - долг
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional, Dict, Any, List
from enum import Enum

from django.db.models import Q, Sum, Count, F, QuerySet
from django.utils import timezone

from stores.models import Store, Region, City
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct
from products.models import Expense  # Расходы партнёров


# =============================================================================
# ENUMS И DATA CLASSES
# =============================================================================

class TimePeriod(str, Enum):
    """Периоды фильтрации (ТЗ v2.0)."""
    DAY = 'day'
    WEEK = 'week'
    MONTH = 'month'
    HALF_YEAR = 'half_year'
    YEAR = 'year'
    ALL_TIME = 'all_time'


@dataclass
class ReportFilters:
    """Фильтры для отчётов."""
    period: TimePeriod = TimePeriod.ALL_TIME
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    store_id: Optional[int] = None
    partner_id: Optional[int] = None
    region_id: Optional[int] = None
    city_id: Optional[int] = None


@dataclass
class StatisticsData:
    """Данные статистики для круговой диаграммы."""

    # Финансовые показатели
    income: Decimal  # Доход (продажи + погашенные долги)
    debt: Decimal  # Непогашенный долг
    paid_debt: Decimal  # Погашенные долги
    defect_amount: Decimal  # Брак
    expenses: Decimal  # Расходы

    # Количественные показатели
    bonus_count: int  # Бонусы (штук)
    orders_count: int  # Заказов
    products_count: int  # Товаров продано

    # Вычисляемые
    total_balance: Decimal  # Общий баланс
    profit: Decimal  # Прибыль (без долга)

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в dict для JSON."""
        return {
            'income': float(self.income),
            'debt': float(self.debt),
            'paid_debt': float(self.paid_debt),
            'defect_amount': float(self.defect_amount),
            'expenses': float(self.expenses),
            'bonus_count': self.bonus_count,
            'orders_count': self.orders_count,
            'products_count': self.products_count,
            'total_balance': float(self.total_balance),
            'profit': float(self.profit),
        }

    def get_chart_data(self) -> Dict[str, float]:
        """
        Данные для круговой диаграммы (ТЗ v2.0).

        Диаграмма показывает: доход, долг, брак, расходы
        """
        return {
            'income': float(self.income),
            'debt': float(self.debt),
            'defect': float(self.defect_amount),
            'expenses': float(self.expenses),
        }


# =============================================================================
# REPORT SERVICE
# =============================================================================

class ReportService:
    """
    Сервис для генерации статистики в реальном времени.

    ТЗ v2.0: "Круговые диаграммы с фильтрацией по датам, магазинам, областям"
    """

    @classmethod
    def get_date_range(
            cls,
            period: TimePeriod,
            start_date: Optional[date] = None,
            end_date: Optional[date] = None,
    ) -> tuple[date, date]:
        """
        Получить диапазон дат для периода.

        Args:
            period: Период (день, неделя, месяц и т.д.)
            start_date: Начальная дата (опционально)
            end_date: Конечная дата (опционально)

        Returns:
            (start_date, end_date)
        """
        today = timezone.now().date()

        if start_date and end_date:
            return start_date, end_date

        if period == TimePeriod.DAY:
            return today, today

        elif period == TimePeriod.WEEK:
            start = today - timedelta(days=today.weekday())  # Понедельник
            end = start + timedelta(days=6)  # Воскресенье
            return start, end

        elif period == TimePeriod.MONTH:
            start = today.replace(day=1)
            # Последний день месяца
            if today.month == 12:
                end = today.replace(day=31)
            else:
                next_month = today.replace(month=today.month + 1, day=1)
                end = next_month - timedelta(days=1)
            return start, end

        elif period == TimePeriod.HALF_YEAR:
            start = today - timedelta(days=180)
            return start, today

        elif period == TimePeriod.YEAR:
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
            return start, end

        elif period == TimePeriod.ALL_TIME:
            # Берём с начала времён до сегодня
            return date(2020, 1, 1), today

        return today, today

    @classmethod
    def calculate_statistics(
            cls,
            filters: ReportFilters,
    ) -> StatisticsData:
        """
        Вычислить статистику в реальном времени (ТЗ v2.0).

        Алгоритм:
        1. Получить диапазон дат
        2. Фильтровать заказы по датам и другим параметрам
        3. Вычислить все показатели
        4. Вернуть StatisticsData

        Args:
            filters: Фильтры

        Returns:
            StatisticsData
        """
        # 1. Диапазон дат
        start_date, end_date = cls.get_date_range(
            period=filters.period,
            start_date=filters.start_date,
            end_date=filters.end_date
        )

        # 2. Базовый queryset заказов (только ACCEPTED)
        orders_qs = StoreOrder.objects.filter(
            status=StoreOrderStatus.ACCEPTED,
            confirmed_at__date__gte=start_date,
            confirmed_at__date__lte=end_date
        )

        # Фильтрация по магазину
        if filters.store_id:
            orders_qs = orders_qs.filter(store_id=filters.store_id)

        # Фильтрация по партнёру
        if filters.partner_id:
            orders_qs = orders_qs.filter(partner_id=filters.partner_id)

        # Фильтрация по региону
        if filters.region_id:
            orders_qs = orders_qs.filter(store__region_id=filters.region_id)

        # Фильтрация по городу
        if filters.city_id:
            orders_qs = orders_qs.filter(store__city_id=filters.city_id)

        # 3. ВЫЧИСЛЕНИЕ ПОКАЗАТЕЛЕЙ

        # === ДОХОД ===
        # Доход = сумма всех заказов (total_amount)
        income_data = orders_qs.aggregate(
            total=Sum('total_amount')
        )
        income = income_data['total'] or Decimal('0')

        # === ДОЛГ (непогашенный) ===
        # Долг = сумма (debt_amount - paid_amount) по всем заказам
        debt_data = orders_qs.aggregate(
            total_debt=Sum('debt_amount'),
            total_paid=Sum('paid_amount')
        )
        total_debt = debt_data['total_debt'] or Decimal('0')
        total_paid_from_orders = debt_data['total_paid'] or Decimal('0')
        debt = max(total_debt - total_paid_from_orders, Decimal('0'))

        # === ПОГАШЕННЫЕ ДОЛГИ ===
        # Погашенные долги = сумма всех DebtPayment в периоде
        paid_debt_qs = DebtPayment.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            order__in=orders_qs
        )
        paid_debt_data = paid_debt_qs.aggregate(total=Sum('amount'))
        paid_debt = paid_debt_data['total'] or Decimal('0')

        # === БОНУСЫ (количество) ===
        # Бонусы = count всех позиций с is_bonus=True
        from orders.models import StoreOrderItem
        bonus_data = StoreOrderItem.objects.filter(
            order__in=orders_qs,
            is_bonus=True
        ).aggregate(count=Count('id'))
        bonus_count = bonus_data['count'] or 0

        # === БРАК ===
        # Брак = сумма всех DefectiveProduct со статусом APPROVED
        defect_qs = DefectiveProduct.objects.filter(
            status=DefectiveProduct.DefectStatus.APPROVED,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            order__in=orders_qs
        )
        defect_data = defect_qs.aggregate(total=Sum('total_amount'))
        defect_amount = defect_data['total'] or Decimal('0')

        # === РАСХОДЫ ===
        # Расходы = сумма всех Expense в периоде
        expenses_qs = Expense.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )

        # Фильтрация расходов по партнёру
        if filters.partner_id:
            expenses_qs = expenses_qs.filter(partner_id=filters.partner_id)

        expenses_data = expenses_qs.aggregate(total=Sum('amount'))
        expenses = expenses_data['total'] or Decimal('0')

        # === КОЛИЧЕСТВЕННЫЕ ПОКАЗАТЕЛИ ===
        orders_count = orders_qs.count()

        products_count_data = StoreOrderItem.objects.filter(
            order__in=orders_qs
        ).aggregate(total=Sum('quantity'))
        products_count = int(products_count_data['total'] or 0)

        # === ВЫЧИСЛЯЕМЫЕ ПОКАЗАТЕЛИ ===
        # Общий баланс = доход - брак - расходы - долг
        total_balance = income - defect_amount - expenses - debt

        # Прибыль (без учёта долга) = доход - брак - расходы
        profit = income - defect_amount - expenses

        # 4. Возвращаем результат
        return StatisticsData(
            income=income,
            debt=debt,
            paid_debt=paid_debt,
            defect_amount=defect_amount,
            expenses=expenses,
            bonus_count=bonus_count,
            orders_count=orders_count,
            products_count=products_count,
            total_balance=total_balance,
            profit=profit,
        )

    @classmethod
    def get_statistics_summary(
            cls,
            filters: ReportFilters,
    ) -> Dict[str, Any]:
        """
        Получить полную статистику с данными для диаграммы.

        Args:
            filters: Фильтры

        Returns:
            Dict с данными для фронтенда
        """
        stats = cls.calculate_statistics(filters)

        start_date, end_date = cls.get_date_range(
            period=filters.period,
            start_date=filters.start_date,
            end_date=filters.end_date
        )

        return {
            'period': {
                'type': filters.period,
                'start_date': str(start_date),
                'end_date': str(end_date),
            },
            'filters': {
                'store_id': filters.store_id,
                'partner_id': filters.partner_id,
                'region_id': filters.region_id,
                'city_id': filters.city_id,
            },
            'statistics': stats.to_dict(),
            'chart_data': stats.get_chart_data(),
        }

    @classmethod
    def get_store_history(
            cls,
            store: Store,
            start_date: date,
            end_date: date,
    ) -> List[Dict[str, Any]]:
        """
        История магазина с фильтрацией по дате (ТЗ v2.0).

        Данные:
        - Полученные товары (название, количество, цена)
        - Бонусные товары (бесплатные)
        - Бракованные товары (уменьшают долг)
        - Долг магазина
        - Общие данные (все товары за день)

        Args:
            store: Магазин
            start_date: Начальная дата
            end_date: Конечная дата

        Returns:
            List[Dict] с данными по дням
        """
        history = []

        # Получаем все заказы магазина в периоде
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED,
            confirmed_at__date__gte=start_date,
            confirmed_at__date__lte=end_date
        ).prefetch_related('items__product')

        for order in orders:
            day_data = {
                'date': order.confirmed_at.date(),
                'order_id': order.id,
                'products': [],
                'bonus_products': [],
                'defective_products': [],
                'debt': float(order.debt_amount),
                'paid': float(order.paid_amount),
                'outstanding_debt': float(order.outstanding_debt),
            }

            # Полученные товары
            for item in order.items.all():
                product_data = {
                    'name': item.product.name,
                    'quantity': float(item.quantity),
                    'price': float(item.price),
                    'total': float(item.total),
                }

                if item.is_bonus:
                    day_data['bonus_products'].append(product_data)
                else:
                    day_data['products'].append(product_data)

            # Бракованные товары
            defects = DefectiveProduct.objects.filter(
                order=order,
                status=DefectiveProduct.DefectStatus.APPROVED
            )

            for defect in defects:
                day_data['defective_products'].append({
                    'name': defect.product.name,
                    'quantity': float(defect.quantity),
                    'amount': float(defect.total_amount),
                    'reason': defect.reason,
                })

            history.append(day_data)

        return history