# apps/reports/services.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Сервисы для статистики и отчётов согласно ТЗ v2.0.

ОСНОВНОЙ СЕРВИС:
- ReportService: Генерация статистики в реальном времени

ТЗ v2.0 ТРЕБОВАНИЯ:
- Круговые диаграммы (доход, долг, брак, расходы)
- Календарная фильтрация (день, неделя, месяц, полгода, год, всё время)
- Фильтрация по магазинам, городам, областям
- Общий баланс: доход - брак - расходы - долг

КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ:
1. Используем PartnerExpense вместо Expense для расходов партнёров
2. Поля date и partner_id теперь корректны
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
from products.models import PartnerExpense  # ✅ ИСПРАВЛЕНО: Было Expense
from products.services import ExpenseService


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
    """
    Данные статистики для круговой диаграммы.

    ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ ERROR-7:
    Поле expenses разделено на:
    - partner_expenses (расходы партнёра, ручной ввод)
    - production_expenses (себестоимость производства)
    - total_expenses (сумма обоих)
    """

    # Финансовые показатели
    income: Decimal  # Доход (продажи + погашенные долги)
    debt: Decimal  # Непогашенный долг
    paid_debt: Decimal  # Погашенные долги
    defect_amount: Decimal  # Брак

    # ✅ НОВОЕ: Разделение расходов
    partner_expenses: Decimal  # Расходы партнёра (ручной ввод)
    production_expenses: Decimal  # Себестоимость производства
    total_expenses: Decimal  # Общая сумма расходов

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

            # ✅ НОВОЕ: Разделённые расходы
            'partner_expenses': float(self.partner_expenses),
            'production_expenses': float(self.production_expenses),
            'total_expenses': float(self.total_expenses),

            'bonus_count': self.bonus_count,
            'orders_count': self.orders_count,
            'products_count': self.products_count,
            'total_balance': float(self.total_balance),
            'profit': float(self.profit),
        }

    def get_chart_data(self) -> Dict[str, float]:
        """
        Данные для круговой диаграммы (ТЗ v2.0).

        ✅ ИЗМЕНЕНИЕ: total_expenses вместо отдельных полей
        """
        return {
            'income': float(self.income),
            'debt': float(self.debt),
            'defect': float(self.defect_amount),
            'expenses': float(self.total_expenses),  # ✅ Общая сумма
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

        ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ ERROR-7:
        Добавлен расчёт production_expenses из ExpenseService

        Алгоритм:
        1. Получить диапазон дат
        2. Фильтровать заказы по датам и другим параметрам
        3. Вычислить все показатели
        4. ✅ НОВОЕ: Рассчитать расходы производства
        5. ✅ НОВОЕ: Разделить на partner_expenses и production_expenses
        6. Вернуть StatisticsData
        """
        # 1. Диапазон дат
        start_date, end_date = cls.get_date_range(
            period=filters.period,
            start_date=filters.start_date,
            end_date=filters.end_date
        )

        # 2. Фильтрация заказов
        orders_qs = StoreOrder.objects.filter(
            status=StoreOrderStatus.ACCEPTED,
            confirmed_at__date__gte=start_date,
            confirmed_at__date__lte=end_date
        )

        # Фильтры
        if filters.store_id:
            orders_qs = orders_qs.filter(store_id=filters.store_id)

        if filters.partner_id:
            orders_qs = orders_qs.filter(partner_id=filters.partner_id)

        if filters.region_id:
            orders_qs = orders_qs.filter(store__region_id=filters.region_id)

        if filters.city_id:
            orders_qs = orders_qs.filter(store__city_id=filters.city_id)

        # 3. Доход (сумма заказов + погашенные долги)
        orders_data = orders_qs.aggregate(total=Sum('total_amount'))
        orders_income = orders_data['total'] or Decimal('0')

        # Погашенные долги
        paid_debt_qs = DebtPayment.objects.filter(
            created_at__date__gte=start_date,  # ✅ ИСПРАВЛЕНО
            created_at__date__lte=end_date  # ✅ ИСПРАВЛЕНО
        )

        if filters.store_id:
            paid_debt_qs = paid_debt_qs.filter(order__store_id=filters.store_id)

        if filters.partner_id:
            paid_debt_qs = paid_debt_qs.filter(received_by_id=filters.partner_id)

        paid_debt_data = paid_debt_qs.aggregate(total=Sum('amount'))
        paid_debt = paid_debt_data['total'] or Decimal('0')

        # Общий доход
        income = orders_income + paid_debt

        # 4. Долги
        debt_data = orders_qs.aggregate(total=Sum('debt_amount'))
        debt = debt_data['total'] or Decimal('0')

        # 5. Бонусы (количество)
        from orders.models import StoreOrderItem
        bonus_data = StoreOrderItem.objects.filter(
            order__in=orders_qs,
            is_bonus=True
        ).aggregate(count=Count('id'))
        bonus_count = bonus_data['count'] or 0

        # 6. Брак
        defect_qs = DefectiveProduct.objects.filter(
            status=DefectiveProduct.DefectStatus.APPROVED,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            order__in=orders_qs
        )
        defect_data = defect_qs.aggregate(total=Sum('total_amount'))
        defect_amount = defect_data['total'] or Decimal('0')

        # =========================================================================
        # ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ ERROR-7: РАЗДЕЛЕНИЕ РАСХОДОВ
        # =========================================================================

        # 7a. РАСХОДЫ ПАРТНЁРОВ (ручной ввод)
        partner_expenses_qs = PartnerExpense.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )

        # Фильтрация расходов по партнёру
        if filters.partner_id:
            partner_expenses_qs = partner_expenses_qs.filter(partner_id=filters.partner_id)

        partner_expenses_data = partner_expenses_qs.aggregate(total=Sum('amount'))
        partner_expenses = partner_expenses_data['total'] or Decimal('0')

        # 7b. РАСХОДЫ ПРОИЗВОДСТВА (себестоимость)
        # Рассчитываем через ExpenseService с учётом иерархии
        try:
            expenses_result = ExpenseService.calculate_total_expenses_with_hierarchy()

            # Себестоимость = дневные расходы * количество дней в периоде
            days_count = (end_date - start_date).days + 1

            # Дневные расходы из Expense
            daily_production = expenses_result.daily_expenses

            # Месячные расходы в пересчёте на период
            monthly_production = expenses_result.monthly_per_day * days_count

            # Общая сумма производственных расходов
            production_expenses = daily_production + monthly_production

        except Exception as e:
            # Если ExpenseService недоступен - используем 0
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Не удалось рассчитать production_expenses: {e}")
            production_expenses = Decimal('0')

        # 7c. ОБЩАЯ СУММА РАСХОДОВ
        total_expenses = partner_expenses + production_expenses

        # =========================================================================
        # КОНЕЦ ИЗМЕНЕНИЙ ERROR-7
        # =========================================================================

        # 8. Количественные показатели
        orders_count = orders_qs.count()

        products_count_data = StoreOrderItem.objects.filter(
            order__in=orders_qs
        ).aggregate(total=Sum('quantity'))
        products_count = int(products_count_data['total'] or 0)

        # 9. Вычисляемые показатели
        # Общий баланс = доход - брак - расходы - долг
        total_balance = income - defect_amount - total_expenses - debt

        # Прибыль (без учёта долга) = доход - брак - расходы
        profit = income - defect_amount - total_expenses

        # 10. Возвращаем результат
        return StatisticsData(
            income=income,
            debt=debt,
            paid_debt=paid_debt,
            defect_amount=defect_amount,

            # ✅ НОВОЕ: Разделённые расходы
            partner_expenses=partner_expenses,
            production_expenses=production_expenses,
            total_expenses=total_expenses,

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
                'type': filters.period.value,
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
            start_date: Optional[date] = None,  # ✅ Теперь опционально
            end_date: Optional[date] = None,  # ✅ Теперь опционально
    ) -> List[Dict[str, Any]]:
        """
        История магазина с фильтрацией по дате (ТЗ v2.0).

        ✅ ИСПРАВЛЕНО:
        - Поле changed_at → created_at
        - start_date и end_date теперь опциональны (по умолчанию за всё время)

        Args:
            store: Магазин
            start_date: Начальная дата (опционально, по умолчанию с начала времён)
            end_date: Конечная дата (опционально, по умолчанию до сегодня)

        Returns:
            List[Dict] с историей магазина
        """
        from orders.models import OrderHistory, OrderType
        from django.db.models import Min

        # =========================================================================
        # ОПРЕДЕЛЕНИЕ ДИАПАЗОНА ДАТ (если не указаны)
        # =========================================================================

        if not start_date:
            # Берём дату первого заказа магазина
            first_order = StoreOrder.objects.filter(
                store=store
            ).order_by('created_at').first()

            if first_order:
                start_date = first_order.created_at.date()
            else:
                # Если заказов нет - берём сегодня
                start_date = timezone.now().date()

        if not end_date:
            # До сегодняшнего дня
            end_date = timezone.now().date()

        history = []

        # =========================================================================
        # 1. ЗАКАЗЫ МАГАЗИНА
        # =========================================================================
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED,
            confirmed_at__date__gte=start_date,
            confirmed_at__date__lte=end_date
        ).prefetch_related(
            'items__product',
            'debt_payments',
        ).select_related('partner')

        for order in orders:
            day_data = {
                'type': 'order',
                'date': order.confirmed_at.date().isoformat(),
                'order_id': order.id,
                'partner_name': order.partner.get_full_name() if order.partner else None,
                'products': [],
                'bonus_products': [],
                'defective_products': [],
                'prepayment_amount': float(order.prepayment_amount),
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
            ).select_related('product')

            for defect in defects:
                day_data['defective_products'].append({
                    'name': defect.product.name,
                    'quantity': float(defect.quantity),
                    'amount': float(defect.total_amount),
                    'reason': defect.reason,
                })

            # Погашения долга по этому заказу
            debt_payments_list = []
            for payment in order.debt_payments.all().order_by('created_at'):  # ✅ ИСПРАВЛЕНО
                debt_payments_list.append({
                    'payment_id': payment.id,
                    'amount': float(payment.amount),
                    'created_at': payment.created_at.isoformat(),  # ✅ ИСПРАВЛЕНО
                    'paid_by': payment.paid_by.get_full_name() if payment.paid_by else None,
                    'received_by': payment.received_by.get_full_name() if payment.received_by else None,
                    'comment': payment.comment or '',
                })

            day_data['debt_payments'] = debt_payments_list

            # История статусов заказа
            status_history_list = []
            order_history = OrderHistory.objects.filter(
                order_type=OrderType.STORE,
                order_id=order.id
            ).order_by('created_at')  # ✅ ИСПРАВЛЕНО: changed_at → created_at

            for history_entry in order_history:
                status_history_list.append({
                    'old_status': history_entry.old_status,
                    'new_status': history_entry.new_status,
                    'changed_by': history_entry.changed_by.get_full_name() if history_entry.changed_by else None,
                    'created_at': history_entry.created_at.isoformat(),  # ✅ ИСПРАВЛЕНО
                    'comment': history_entry.comment or '',
                })

            day_data['status_history'] = status_history_list

            history.append(day_data)

        # =========================================================================
        # 2. ОТДЕЛЬНЫЕ ПОГАШЕНИЯ ДОЛГА (без привязки к заказу)
        # =========================================================================

        # Погашения которые были сделаны напрямую
        standalone_payments = DebtPayment.objects.filter(
            order__store=store,
            created_at__date__gte=start_date,  # ✅ ИСПРАВЛЕНО
            created_at__date__lte=end_date  # ✅ ИСПРАВЛЕНО
        ).select_related('order', 'paid_by', 'received_by').order_by('created_at')  # ✅ ИСПРАВЛЕНО

        # Группируем по дням
        from collections import defaultdict
        payments_by_date = defaultdict(list)

        for payment in standalone_payments:
            payment_date = payment.created_at.date()  # ✅ ИСПРАВЛЕНО

            payments_by_date[payment_date].append({
                'payment_id': payment.id,
                'order_id': payment.order.id if payment.order else None,
                'amount': float(payment.amount),
                'created_at': payment.created_at.isoformat(),  # ✅ ИСПРАВЛЕНО
                'paid_by': payment.paid_by.get_full_name() if payment.paid_by else None,
                'received_by': payment.received_by.get_full_name() if payment.received_by else None,
                'comment': payment.comment or '',
            })

        # Добавляем дни с погашениями в историю
        for payment_date, payments_list in payments_by_date.items():
            history.append({
                'type': 'payment',
                'date': payment_date.isoformat(),
                'payments': payments_list,
                'total_amount': sum(p['amount'] for p in payments_list),
            })

        # Сортируем всю историю по дате
        history.sort(key=lambda x: x['date'], reverse=True)

        return history

    @classmethod
    def get_partner_expenses_summary(
            cls,
            partner_id: Optional[int] = None,
            start_date: Optional[date] = None,
            end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Сводка по расходам партнёров.

        Args:
            partner_id: ID партнёра (опционально, если None - все партнёры)
            start_date: Начальная дата
            end_date: Конечная дата

        Returns:
            Dict с суммой и количеством расходов
        """
        today = timezone.now().date()
        start_date = start_date or today.replace(day=1)
        end_date = end_date or today

        expenses_qs = PartnerExpense.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )

        if partner_id:
            expenses_qs = expenses_qs.filter(partner_id=partner_id)

        stats = expenses_qs.aggregate(
            total_amount=Sum('amount'),
            count=Count('id')
        )

        return {
            'period': {
                'start_date': str(start_date),
                'end_date': str(end_date),
            },
            'partner_id': partner_id,
            'total_amount': float(stats['total_amount'] or 0),
            'expenses_count': stats['count'] or 0,
        }
