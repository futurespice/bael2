# apps/reports/services.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.1
"""
Сервисы для статистики и отчётов согласно ТЗ v2.0.

КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ v2.1:
1. ✅ ИСПРАВЛЕНО: Бонусы считаются из ИНВЕНТАРЯ, а не из заказов
2. ✅ ИСПРАВЛЕНО: Брак фильтруется по дате создания, а не по заказам
3. ✅ УЛУЧШЕНО: Расходы разделены на партнёрские и производственные

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

from stores.models import Store, Region, City, StoreInventory
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct, StoreOrderItem
from products.models import PartnerExpense
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

    ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ v2.1:
    - bonus_count теперь считается из ИНВЕНТАРЯ, а не из заказов
    - defect_amount фильтруется по дате создания, а не по заказам
    """

    # Финансовые показатели
    income: Decimal  # Доход (продажи + погашенные долги)
    debt: Decimal  # Непогашенный долг
    paid_debt: Decimal  # Погашенные долги
    defect_amount: Decimal  # Брак

    # Расходы
    partner_expenses: Decimal  # Расходы партнёра (ручной ввод)
    production_expenses: Decimal  # Себестоимость производства
    total_expenses: Decimal  # Общая сумма расходов

    # Количественные показатели
    bonus_count: int  # ✅ ИСПРАВЛЕНО: Бонусы из инвентаря
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

            # Разделённые расходы
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

        Возвращает только 4 основных показателя:
        - income (доход)
        - debt (долг)
        - defect (брак)
        - expenses (расходы)
        """
        return {
            'income': float(self.income),
            'debt': float(self.debt),
            'defect': float(self.defect_amount),
            'expenses': float(self.total_expenses),
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
            start_date: Начало (опционально)
            end_date: Конец (опционально)

        Returns:
            (start_date, end_date)
        """
        today = timezone.now().date()

        if start_date and end_date:
            return start_date, end_date

        if period == TimePeriod.DAY:
            return today, today

        elif period == TimePeriod.WEEK:
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            return start, end

        elif period == TimePeriod.MONTH:
            start = today.replace(day=1)
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

        else:  # ALL_TIME
            # Берём от самого раннего заказа
            first_order = StoreOrder.objects.order_by('created_at').first()
            if first_order:
                return first_order.created_at.date(), today
            return today, today

    @classmethod
    def calculate_statistics(
            cls,
            filters: ReportFilters,
    ) -> StatisticsData:
        """
        Рассчитать статистику с учётом фильтров.

        ✅ КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ v2.1:
        1. Бонусы считаются из ИНВЕНТАРЯ магазинов (не из заказов)
        2. Брак фильтруется по дате создания (не по заказам)
        3. Расходы разделены на partner_expenses и production_expenses

        Алгоритм:
        1. Получить диапазон дат
        2. Фильтровать заказы по датам и другим параметрам
        3. Вычислить все показатели
        4. Рассчитать бонусы из инвентаря магазинов
        5. Фильтровать брак по дате создания
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

        # Применяем фильтры
        if filters.store_id:
            orders_qs = orders_qs.filter(store_id=filters.store_id)

        if filters.partner_id:
            orders_qs = orders_qs.filter(partner_id=filters.partner_id)

        if filters.region_id:
            orders_qs = orders_qs.filter(store__region_id=filters.region_id)

        if filters.city_id:
            orders_qs = orders_qs.filter(store__city_id=filters.city_id)

        # =========================================================================
        # 3. ДОХОД (сумма заказов + погашенные долги)
        # =========================================================================

        orders_data = orders_qs.aggregate(total=Sum('total_amount'))
        orders_income = orders_data['total'] or Decimal('0')

        # Погашенные долги
        paid_debt_qs = DebtPayment.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )

        if filters.store_id:
            paid_debt_qs = paid_debt_qs.filter(order__store_id=filters.store_id)

        if filters.partner_id:
            paid_debt_qs = paid_debt_qs.filter(received_by_id=filters.partner_id)

        paid_debt_data = paid_debt_qs.aggregate(total=Sum('amount'))
        paid_debt = paid_debt_data['total'] or Decimal('0')

        # Общий доход
        income = orders_income + paid_debt

        # =========================================================================
        # 4. ДОЛГИ (непогашенные)
        # =========================================================================

        debt_data = orders_qs.aggregate(total=Sum('debt_amount'))
        debt = debt_data['total'] or Decimal('0')

        # =========================================================================
        # 5. ✅ БОНУСЫ - ИСПРАВЛЕНО v2.1
        # Считаем из ИНВЕНТАРЯ магазинов, а не из заказов!
        # =========================================================================

        bonus_count = 0

        # Определяем магазины для подсчёта
        if filters.store_id:
            stores = Store.objects.filter(id=filters.store_id, is_active=True)
        else:
            stores = Store.objects.filter(is_active=True)

            # Применяем дополнительные фильтры
            if filters.region_id:
                stores = stores.filter(region_id=filters.region_id)

            if filters.city_id:
                stores = stores.filter(city_id=filters.city_id)

        # Считаем бонусы в инвентаре каждого магазина
        BONUS_THRESHOLD = 21  # Каждый 21-й товар

        for store in stores:
            # Получаем инвентарь магазина
            inventory = StoreInventory.objects.filter(
                store=store
            ).select_related('product')

            for item in inventory:
                product = item.product

                # Бонусы только для штучных товаров с is_bonus=True
                if product.is_bonus and not product.is_weight_based:
                    quantity = int(item.quantity)
                    # Каждый 21-й товар бесплатно
                    item_bonus_count = quantity // BONUS_THRESHOLD
                    bonus_count += item_bonus_count

        # =========================================================================
        # 6. ✅ БРАК - ИСПРАВЛЕНО v2.1
        # Фильтруем по дате СОЗДАНИЯ брака, а не по заказам!
        # =========================================================================

        defect_qs = DefectiveProduct.objects.filter(
            status=DefectiveProduct.DefectStatus.APPROVED,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )

        # Применяем фильтры
        if filters.store_id:
            defect_qs = defect_qs.filter(order__store_id=filters.store_id)

        if filters.partner_id:
            defect_qs = defect_qs.filter(reviewed_by_id=filters.partner_id)

        if filters.region_id:
            defect_qs = defect_qs.filter(order__store__region_id=filters.region_id)

        if filters.city_id:
            defect_qs = defect_qs.filter(order__store__city_id=filters.city_id)

        defect_data = defect_qs.aggregate(total=Sum('total_amount'))
        defect_amount = defect_data['total'] or Decimal('0')

        # =========================================================================
        # 7. РАСХОДЫ (разделённые)
        # =========================================================================

        # 7a. РАСХОДЫ ПАРТНЁРОВ (ручной ввод)
        partner_expenses_qs = PartnerExpense.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )

        if filters.partner_id:
            partner_expenses_qs = partner_expenses_qs.filter(partner_id=filters.partner_id)

        partner_expenses_data = partner_expenses_qs.aggregate(total=Sum('amount'))
        partner_expenses = partner_expenses_data['total'] or Decimal('0')

        # 7b. РАСХОДЫ ПРОИЗВОДСТВА (себестоимость)
        try:
            expenses_result = ExpenseService.calculate_total_expenses_with_hierarchy()

            # Количество дней в периоде
            days_count = (end_date - start_date).days + 1

            # Дневные расходы * количество дней
            daily_production = expenses_result.daily_expenses * days_count

            # Месячные расходы в пересчёте на период
            monthly_production = expenses_result.monthly_per_day * days_count

            # Общая сумма производственных расходов
            production_expenses = daily_production + monthly_production

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Не удалось рассчитать production_expenses: {e}")
            production_expenses = Decimal('0')

        # 7c. ОБЩАЯ СУММА РАСХОДОВ
        total_expenses = partner_expenses + production_expenses

        # =========================================================================
        # 8. КОЛИЧЕСТВЕННЫЕ ПОКАЗАТЕЛИ
        # =========================================================================

        orders_count = orders_qs.count()

        products_count_data = StoreOrderItem.objects.filter(
            order__in=orders_qs
        ).aggregate(total=Sum('quantity'))
        products_count = int(products_count_data['total'] or 0)

        # =========================================================================
        # 9. ВЫЧИСЛЯЕМЫЕ ПОКАЗАТЕЛИ
        # =========================================================================

        # Общий баланс = доход - брак - расходы - долг
        total_balance = income - defect_amount - total_expenses - debt

        # Прибыль (без учёта долга) = доход - брак - расходы
        profit = income - defect_amount - total_expenses

        # =========================================================================
        # 10. ВОЗВРАЩАЕМ РЕЗУЛЬТАТ
        # =========================================================================

        return StatisticsData(
            income=income,
            debt=debt,
            paid_debt=paid_debt,
            defect_amount=defect_amount,

            # Разделённые расходы
            partner_expenses=partner_expenses,
            production_expenses=production_expenses,
            total_expenses=total_expenses,

            bonus_count=bonus_count,  # ✅ ИСПРАВЛЕНО: из инвентаря
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
            start_date: Optional[date] = None,
            end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        История магазина с фильтрацией по дате (ТЗ v2.0).

        Args:
            store: Магазин
            start_date: Начало периода (опционально)
            end_date: Конец периода (опционально)

        Returns:
            List[Dict] с историей по дням
        """
        from orders.models import StoreOrderItem, OrderHistory, OrderType

        # Получаем заказы магазина
        orders_qs = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED
        ).order_by('confirmed_at')

        # Применяем фильтр по датам
        if start_date:
            orders_qs = orders_qs.filter(confirmed_at__date__gte=start_date)

        if end_date:
            orders_qs = orders_qs.filter(confirmed_at__date__lte=end_date)

        # Группируем заказы по дням
        history = []

        for order in orders_qs:
            order_date = order.confirmed_at.date()

            # Ищем существующую запись за этот день
            day_data = next(
                (item for item in history if item['date'] == str(order_date)),
                None
            )

            if not day_data:
                day_data = {
                    'date': str(order_date),
                    'orders': [],
                    'products': [],
                    'bonus_products': [],
                    'defective_products': [],
                    'debt_payments': [],
                    'status_history': [],
                    'total_amount': 0.0,
                    'total_debt': 0.0,
                }
                history.append(day_data)

            # Добавляем информацию о заказе
            day_data['orders'].append({
                'order_id': order.id,
                'total_amount': float(order.total_amount),
                'debt_amount': float(order.debt_amount),
                'prepayment_amount': float(order.prepayment_amount),
                'partner_name': order.partner.get_full_name() if order.partner else 'Не назначен',
            })

            day_data['total_amount'] += float(order.total_amount)
            day_data['total_debt'] += float(order.debt_amount)

            # Товары заказа
            items = order.items.all().select_related('product')

            for item in items:
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
            for payment in order.debt_payments.all().order_by('created_at'):
                debt_payments_list.append({
                    'payment_id': payment.id,
                    'amount': float(payment.amount),
                    'created_at': payment.created_at.isoformat(),
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
            ).order_by('created_at')

            for history_entry in order_history:
                status_history_list.append({
                    'old_status': history_entry.old_status,
                    'new_status': history_entry.new_status,
                    'changed_by': history_entry.changed_by.get_full_name() if history_entry.changed_by else None,
                    'created_at': history_entry.created_at.isoformat(),
                    'comment': history_entry.comment or '',
                })

            day_data['status_history'] = status_history_list

        return history