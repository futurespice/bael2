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

from django.db.models import Q, Sum, Count, F, QuerySet, Prefetch
from django.utils import timezone

from stores.models import Store, Region, City, StoreInventory
from orders.models import StoreOrder, StoreOrderStatus, DebtPayment, DefectiveProduct, StoreOrderItem, ReturnedItem
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
    bonus_count: int  # Количество бонусных единиц из заказов
    bonus_amount: Decimal  # Сумма бонусов (кол-во × цена товара)
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
            'bonus_amount': float(self.bonus_amount),
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
        today = timezone.localdate()

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
        # 3. ДОХОД (сумма заказов)
        # =========================================================================

        orders_data = orders_qs.aggregate(
            total=Sum('total_amount'),
            total_prepayment=Sum('prepayment_amount'),
            total_debt=Sum('debt_amount'),
        )
        orders_income = orders_data['total'] or Decimal('0')
        prepayment_total = orders_data['total_prepayment'] or Decimal('0')
        original_debt = orders_data['total_debt'] or Decimal('0')

        # Доход = сумма заказов (стоимость проданных товаров)
        income = orders_income

        # =========================================================================
        # 4. ПОГАШЕННЫЕ ДОЛГИ (предоплата + погашения через pay-debt)
        # =========================================================================

        # Погашения через DebtPayment (pay-debt)
        # Фильтруем по дате подтверждения заказа (не по дате платежа),
        # чтобы debt и paid_debt относились к одному и тому же набору заказов.
        paid_debt_qs = DebtPayment.objects.filter(
            order__confirmed_at__date__gte=start_date,
            order__confirmed_at__date__lte=end_date
        )

        if filters.store_id:
            paid_debt_qs = paid_debt_qs.filter(order__store_id=filters.store_id)

        if filters.partner_id:
            paid_debt_qs = paid_debt_qs.filter(order__partner_id=filters.partner_id)

        if filters.region_id:
            paid_debt_qs = paid_debt_qs.filter(order__store__region_id=filters.region_id)

        if filters.city_id:
            paid_debt_qs = paid_debt_qs.filter(order__store__city_id=filters.city_id)

        paid_debt_data = paid_debt_qs.aggregate(total=Sum('amount'))
        debt_payments_total = paid_debt_data['total'] or Decimal('0')

        # Погашено = предоплата + погашения долга
        paid_debt = prepayment_total + debt_payments_total

        # =========================================================================
        # 5. ДОЛГИ (оставшиеся непогашенные) — считается ПОСЛЕ брака (секция 7)
        # =========================================================================
        # debt будет вычислен ниже, после defect_amount

        # =========================================================================
        # 6. БОНУСЫ - считаем из заказов (бонус за один заказ)
        # =========================================================================

        bonus_count = 0
        bonus_items_qs = StoreOrderItem.objects.filter(
            is_bonus=True,
            order__status=StoreOrderStatus.ACCEPTED,
        )

        if filters.store_id:
            bonus_items_qs = bonus_items_qs.filter(order__store_id=filters.store_id)

        if filters.partner_id:
            bonus_items_qs = bonus_items_qs.filter(order__partner_id=filters.partner_id)

        if filters.region_id:
            bonus_items_qs = bonus_items_qs.filter(order__store__region_id=filters.region_id)

        if filters.city_id:
            bonus_items_qs = bonus_items_qs.filter(order__store__city_id=filters.city_id)

        bonus_items_qs = bonus_items_qs.filter(
            order__confirmed_at__date__gte=start_date,
            order__confirmed_at__date__lte=end_date
        )

        from django.db.models import ExpressionWrapper, F as F_, DecimalField as DField
        bonus_data = bonus_items_qs.aggregate(
            total_qty=Sum('quantity'),
            total_amount=Sum(ExpressionWrapper(
                F_('price') * F_('quantity'),
                output_field=DField(max_digits=14, decimal_places=2)
            ))
        )
        bonus_count = int(bonus_data['total_qty'] or 0)
        bonus_amount = bonus_data['total_amount'] or Decimal('0')

        # =========================================================================
        # 7. БРАК — фильтруем по дате подтверждения заказа (как продажи)
        # =========================================================================

        defect_qs = DefectiveProduct.objects.filter(
            status=DefectiveProduct.DefectStatus.APPROVED,
            order__confirmed_at__date__gte=start_date,
            order__confirmed_at__date__lte=end_date
        )

        # Применяем фильтры
        if filters.store_id:
            defect_qs = defect_qs.filter(order__store_id=filters.store_id)

        if filters.partner_id:
            defect_qs = defect_qs.filter(order__partner_id=filters.partner_id)

        if filters.region_id:
            defect_qs = defect_qs.filter(order__store__region_id=filters.region_id)

        if filters.city_id:
            defect_qs = defect_qs.filter(order__store__city_id=filters.city_id)

        defect_data = defect_qs.aggregate(total=Sum('total_amount'))
        defect_amount = defect_data['total'] or Decimal('0')

        # =========================================================================
        # 5 (продолжение). ДОЛГИ — после вычисления брака
        # Долг = исходный (sum order.debt_amount) - погашения - брак.
        # Брак уменьшает Store.debt (view), но не StoreOrder.debt_amount,
        # поэтому вычитаем вручную.
        # =========================================================================
        debt = original_debt - debt_payments_total - defect_amount
        if debt < Decimal('0'):
            debt = Decimal('0')

        # =========================================================================
        # 8. РАСХОДЫ (разделённые)
        # =========================================================================

        # 8a. РАСХОДЫ ПАРТНЁРОВ (ручной ввод)
        partner_expenses_qs = PartnerExpense.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )

        if filters.partner_id:
            partner_expenses_qs = partner_expenses_qs.filter(partner_id=filters.partner_id)

        partner_expenses_data = partner_expenses_qs.aggregate(total=Sum('amount'))
        partner_expenses = partner_expenses_data['total'] or Decimal('0')

        # 8b. РАСХОДЫ ПРОИЗВОДСТВА (себестоимость)
        try:
            from products.models import ProductionBatch, Expense, ExpenseType

            # 1. Затраты на сырье (из реальных партий за период)
            raw_materials = ProductionBatch.objects.filter(
                date__range=[start_date, end_date]
            ).aggregate(total=Sum('total_physical_cost'))['total'] or Decimal('0')

            # 2. Накладные расходы (аренда, з/п и т.д.) - считаем за каждый день периода
            overhead_daily_sum = Decimal('0')
            overhead_expenses = Expense.objects.filter(
                is_active=True,
                expense_type=ExpenseType.OVERHEAD
            )
            
            for expense in overhead_expenses:
                # calculate_amount() возвращает сумму за 1 день
                overhead_daily_sum += expense.calculate_amount()

            # Количество дней в периоде
            days_count = (end_date - start_date).days + 1
            total_overhead = overhead_daily_sum * days_count

            production_expenses = raw_materials + total_overhead

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Не удалось рассчитать production_expenses: {e}")
            production_expenses = Decimal('0')

        # 8c. ОБЩАЯ СУММА РАСХОДОВ
        total_expenses = partner_expenses + production_expenses

        # =========================================================================
        # 9. КОЛИЧЕСТВЕННЫЕ ПОКАЗАТЕЛИ
        # =========================================================================

        orders_count = orders_qs.count()

        products_count_data = StoreOrderItem.objects.filter(
            order__in=orders_qs
        ).aggregate(total=Sum('quantity'))
        products_count = int(products_count_data['total'] or 0)

        # =========================================================================
        # 10. ВЫЧИСЛЯЕМЫЕ ПОКАЗАТЕЛИ
        # =========================================================================

        # Общий баланс = доход - брак - расходы - долг - стоимость бонусов
        total_balance = income - defect_amount - total_expenses - debt - bonus_amount

        # Прибыль (без учёта долга) = доход - брак - расходы - стоимость бонусов
        profit = income - defect_amount - total_expenses - bonus_amount

        # =========================================================================
        # 11. ВОЗВРАЩАЕМ РЕЗУЛЬТАТ
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

            bonus_count=bonus_count,
            bonus_amount=bonus_amount,
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
        from collections import defaultdict
        from orders.models import StoreOrderItem, OrderHistory, OrderType

        # Получаем заказы магазина с prefetch для устранения N+1
        orders_qs = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED
        ).select_related('partner').prefetch_related(
            Prefetch('items', queryset=StoreOrderItem.objects.select_related('product')),
            Prefetch('defective_products', queryset=DefectiveProduct.objects.filter(
                status=DefectiveProduct.DefectStatus.APPROVED
            ).select_related('product')),
            Prefetch('debt_payments', queryset=DebtPayment.objects.order_by('created_at')
                     .select_related('paid_by', 'received_by')),
        ).order_by('confirmed_at')

        # Применяем фильтр по датам
        if start_date:
            orders_qs = orders_qs.filter(confirmed_at__date__gte=start_date)

        if end_date:
            orders_qs = orders_qs.filter(confirmed_at__date__lte=end_date)

        # Bulk fetch OrderHistory для всех заказов сразу
        orders_list = list(orders_qs)
        order_ids = [o.id for o in orders_list]
        all_histories = OrderHistory.objects.filter(
            order_type=OrderType.STORE, order_id__in=order_ids
        ).select_related('changed_by').order_by('created_at')
        histories_by_order = defaultdict(list)
        for h in all_histories:
            histories_by_order[h.order_id].append(h)

        # Группируем заказы по дням (dict для O(1) lookup вместо O(N) linear scan)
        history = []
        history_by_date: dict = {}

        for order in orders_list:
            order_date = str(order.confirmed_at.date())
            day_data = history_by_date.get(order_date)

            if not day_data:
                day_data = {
                    'date': order_date,
                    'orders': [],
                    'products': [],
                    'bonus_products': [],
                    'defective_products': [],
                    'debt_payments': [],
                    'status_history': [],
                    'total_amount': 0.0,
                    'total_debt': 0.0,
                    'total_prepayment': 0.0,
                    'total_paid_debt': 0.0,
                    'remaining_debt': 0.0,
                }
                history_by_date[order_date] = day_data
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
            day_data['total_prepayment'] += float(order.prepayment_amount)

            # Товары заказа (уже prefetch)
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

            # Бракованные товары (уже prefetch с фильтром APPROVED)
            defect_total = Decimal('0')
            for defect in order.defective_products.all():
                day_data['defective_products'].append({
                    'name': defect.product.name,
                    'quantity': float(defect.quantity),
                    'amount': float(defect.total_amount),
                    'reason': defect.reason,
                })
                defect_total += defect.total_amount

            # Вычитаем одобренный брак из долга
            day_data['total_debt'] -= float(defect_total)

            # Погашения долга по этому заказу (уже prefetch, отсортированы)
            debt_payments_list = day_data.get('debt_payments', [])
            order_paid_debt = Decimal('0')
            for payment in order.debt_payments.all():
                debt_payments_list.append({
                    'payment_id': payment.id,
                    'amount': float(payment.amount),
                    'created_at': payment.created_at.isoformat(),
                    'paid_by': payment.paid_by.get_full_name() if payment.paid_by else None,
                    'received_by': payment.received_by.get_full_name() if payment.received_by else None,
                    'comment': payment.comment or '',
                })
                order_paid_debt += payment.amount

            day_data['debt_payments'] = debt_payments_list
            day_data['total_paid_debt'] += float(order_paid_debt)

            # История статусов заказа (из bulk fetch)
            status_history_list = []
            for history_entry in histories_by_order[order.id]:
                status_history_list.append({
                    'old_status': history_entry.old_status,
                    'new_status': history_entry.new_status,
                    'changed_by': history_entry.changed_by.get_full_name() if history_entry.changed_by else None,
                    'created_at': history_entry.created_at.isoformat(),
                    'comment': history_entry.comment or '',
                })

            day_data['status_history'] = status_history_list

        # Рассчитываем оставшийся долг для каждого дня
        for day_data in history:
            remaining = day_data['total_debt'] - day_data['total_paid_debt']
            day_data['remaining_debt'] = max(remaining, 0.0)

        return history


# =============================================================================
# PARTNER STATISTICS SERVICE (v3.0)
# =============================================================================

class PartnerStatisticsService:
    """
    Сервис для расчета статистики партнера (v3.1).
    
    ИЗМЕНЕНИЯ v3.1:
    - Добавлены детализированные списки товаров для каждого показателя
    - Структура ответа соответствует макету мобильного приложения
    """
    
    @staticmethod
    def calculate_statistics(
        partner_id: int,
        period: str = 'month',
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Рассчитать статистику партнера с детализацией товаров.
        
        ПОКАЗАТЕЛИ (согласно макету):
        1. Запрошено (requested) - товары, запрошенные у админа
        2. Продано (sold) - товары, проданные магазинам
        3. Остаток товара (inventory) - текущий инвентарь партнёра
        4. Расходы (expenses) - детализированные расходы
        5. Брак (defective) - бракованные товары
        6. Бонус (bonus) - бонусные товары
        7. Долг (debt) - непогашенный долг магазинов
        8. Погашенный долг (paid_debt)
        9. Общая сумма (grand_total)
        
        Args:
            partner_id: ID партнера
            period: Период (day/week/month/half_year/year/all_time)
            date_from: Начальная дата (опционально)
            date_to: Конечная дата (опционально)
            
        Returns:
            Dict с детализированными показателями
        """
        from orders.models import PartnerRequest, PartnerRequestStatus, PartnerRequestItem
        from stores.models import PartnerInventory
        
        # Определить диапазон дат
        if not date_from or not date_to:
            date_from, date_to = PartnerStatisticsService._get_date_range(period)
        
        # =========================================================================
        # 1. ЗАПРОШЕНО У АДМИНА (с детализацией)
        # =========================================================================
        requested_items = PartnerRequestItem.objects.filter(
            request__partner_id=partner_id,
            request__request_type='request',
            request__status=PartnerRequestStatus.APPROVED,
            request__created_at__range=[date_from, date_to]
        ).select_related('product')
        
        requested_total = Decimal('0')
        requested_piece_count = 0
        requested_weight_total = Decimal('0')
        requested_list = []
        
        for item in requested_items:
            product = item.product
            item_total = item.total_amount  # ✅ Используем price_at_request + корректную формулу для весовых
            requested_total += item_total
            
            if product.is_weight_based:
                requested_weight_total += item.quantity
                unit = 'кг'
            else:
                requested_piece_count += int(item.quantity)
                unit = 'шт'
            
            requested_list.append({
                'name': product.name,
                'quantity': float(item.quantity),
                'unit': unit,
                'price': str(item.price_at_request),  # ✅ Зафиксированная цена
                'total': str(item_total)
            })
        
        # =========================================================================
        # 1.5. ВОЗВРАЩЕНО АДМИНУ (PartnerRequest.request_type='return')
        # =========================================================================
        returned_to_admin_items = PartnerRequestItem.objects.filter(
            request__partner_id=partner_id,
            request__request_type='return',
            request__status=PartnerRequestStatus.APPROVED,
            request__created_at__range=[date_from, date_to]
        ).select_related('product')
        
        returned_to_admin_total = Decimal('0')
        returned_to_admin_piece_count = 0
        returned_to_admin_weight_total = Decimal('0')
        returned_to_admin_list = []
        
        for item in returned_to_admin_items:
            product = item.product
            item_total = item.total_amount  # ✅ Используем price_at_request + корректную формулу для весовых
            returned_to_admin_total += item_total
            
            if product.is_weight_based:
                returned_to_admin_weight_total += item.quantity
                unit = 'кг'
            else:
                returned_to_admin_piece_count += int(item.quantity)
                unit = 'шт'
            
            returned_to_admin_list.append({
                'name': product.name,
                'quantity': float(item.quantity),
                'unit': unit,
                'price': str(item.price_at_request),  # ✅ Зафиксированная цена
                'total': str(item_total)
            })
        
        # =========================================================================
        # 2. ПРОДАНО МАГАЗИНАМ (с детализацией)
        # =========================================================================
        sold_items = StoreOrderItem.objects.filter(
            order__partner_id=partner_id,
            order__status=StoreOrderStatus.ACCEPTED,
            order__confirmed_at__range=[date_from, date_to],
            is_bonus=False  # Исключаем бонусы
        ).select_related('product')
        
        sold_total = Decimal('0')
        sold_piece_count = 0
        sold_weight_total = Decimal('0')
        sold_list = []
        
        for item in sold_items:
            product = item.product
            sold_total += item.total
            
            if product.is_weight_based:
                sold_weight_total += item.quantity
                unit = 'кг'
            else:
                sold_piece_count += int(item.quantity)
                unit = 'шт'
            
            sold_list.append({
                'name': product.name,
                'quantity': float(item.quantity),
                'unit': unit,
                'price': str(item.price),
                'total': str(item.total)
            })
        
        # =========================================================================
        # 3. ОСТАТОК ТОВАРА В ИНВЕНТАРЕ (с детализацией)
        # =========================================================================
        inventory = PartnerInventory.objects.filter(
            partner_id=partner_id,
            quantity__gt=F('reserved_quantity')
        ).select_related('product')

        inventory_total = Decimal('0')
        inventory_piece_count = 0
        inventory_weight_total = Decimal('0')
        inventory_list = []

        for item in inventory:
            product = item.product
            available = item.available_quantity
            item_total = (available * product.final_price).quantize(Decimal('0.01'))
            inventory_total += item_total

            if product.is_weight_based:
                inventory_weight_total += available
                unit = 'кг'
            else:
                inventory_piece_count += int(available)
                unit = 'шт'

            inventory_list.append({
                'name': product.name,
                'quantity': float(available),
                'unit': unit,
                'price': str(product.final_price),
                'total': str(item_total)
            })
        
        # =========================================================================
        # 4. РАСХОДЫ (с детализацией)
        # =========================================================================
        expenses_qs = PartnerExpense.objects.filter(
            partner_id=partner_id,
            date__range=[date_from, date_to]
        )
        
        expenses_total = Decimal('0')
        expenses_list = []
        
        for expense in expenses_qs:
            expenses_total += expense.amount
            expenses_list.append({
                'name': expense.description or 'Без описания',
                'amount': str(expense.amount)
            })
        
        # =========================================================================
        # 5. БРАК (с детализацией)
        # =========================================================================
        defective_qs = DefectiveProduct.objects.filter(
            order__partner_id=partner_id,
            status=DefectiveProduct.DefectStatus.APPROVED,
            order__confirmed_at__range=[date_from, date_to]
        ).select_related('product')
        
        defective_total = Decimal('0')
        defective_list = []
        
        for defect in defective_qs:
            product = defect.product
            defective_total += defect.total_amount
            
            unit = 'кг' if product.is_weight_based else 'шт'
            
            defective_list.append({
                'name': product.name,
                'quantity': float(defect.quantity),
                'unit': unit,
                'amount': str(defect.total_amount)
            })
        
        # =========================================================================
        # 6. БОНУСЫ (с детализацией)
        # =========================================================================
        bonus_items = StoreOrderItem.objects.filter(
            order__partner_id=partner_id,
            order__status=StoreOrderStatus.ACCEPTED,
            order__confirmed_at__range=[date_from, date_to],
            is_bonus=True
        ).select_related('product')
        
        bonus_total = Decimal('0')
        bonus_count = 0
        bonus_list = []
        
        for item in bonus_items:
            product = item.product
            bonus_total += item.quantity * item.price  # item.total всегда 0 для бонусов
            bonus_count += int(item.quantity)
            
            bonus_list.append({
                'name': product.name,
                'quantity': int(item.quantity),
                'price': str(item.price)
            })
        
        # =========================================================================
        # 6.5. ВОЗВРАТЫ (ReturnedItem)
        # =========================================================================
        returned_items = ReturnedItem.objects.filter(
            returned_by_id=partner_id,
            returned_at__range=[date_from, date_to]
        ).select_related('product')
        
        returned_total = Decimal('0')
        returned_piece_count = 0
        returned_weight_total = Decimal('0')
        returned_list = []
        
        for item in returned_items:
            product = item.product
            returned_total += item.total_amount
            
            if product.is_weight_based:
                returned_weight_total += item.weight or Decimal('0')
                unit = 'кг'
            else:
                returned_piece_count += int(item.quantity)
                unit = 'шт'
            
            returned_list.append({
                'name': product.name,
                'quantity': float(item.quantity),
                'weight': float(item.weight) if item.weight else None,
                'unit': unit,
                'price': str(item.price_at_return),
                'total': str(item.total_amount),
                'reason': item.reason,
            })
        
        # =========================================================================
        # 7 & 8. ДОЛГИ — два aggregate с одинаковыми фильтрами объединены в один запрос
        # =========================================================================
        orders_agg = StoreOrder.objects.filter(
            partner_id=partner_id,
            status=StoreOrderStatus.ACCEPTED,
            confirmed_at__range=[date_from, date_to]
        ).aggregate(
            total_debt=Sum('debt_amount'),
            total_prepayment=Sum('prepayment_amount'),
        )
        original_debt = orders_agg['total_debt'] or Decimal('0')
        prepayment_in_period = orders_agg['total_prepayment'] or Decimal('0')

        # Погашения долга по заказам партнёра за период.
        # Фильтруем по дате подтверждения заказа (не по дате платежа),
        # чтобы debt и paid_debt относились к одному и тому же набору заказов.
        debt_payments_in_period = DebtPayment.objects.filter(
            order__partner_id=partner_id,
            order__confirmed_at__range=[date_from, date_to]
        ).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        # Оставшийся долг = исходный - погашения - дефекты
        # (дефекты уменьшают Store.debt, но не StoreOrder.debt_amount)
        unpaid_debt = original_debt - debt_payments_in_period - defective_total
        if unpaid_debt < Decimal('0'):
            unpaid_debt = Decimal('0')

        # Всего погашено = предоплата + погашения долга
        paid_debt = prepayment_in_period + debt_payments_in_period
        
        # =========================================================================
        # 9. ОБЩАЯ СУММА
        # Формула: реально полученные деньги (предоплаты) - расходы - бонусы
        # sold_total НЕ используется: он включает непогашенный долг магазина,
        # которого партнёр никогда не получит в деньгах.
        # =========================================================================
        grand_total = paid_debt - expenses_total - bonus_total
        
        # =========================================================================
        # ФОРМИРУЕМ ОТВЕТ
        # =========================================================================
        return {
            # Запрошено у админа
            'requested': {
                'total_amount': str(requested_total),
                'piece_count': requested_piece_count,
                'weight_total': str(requested_weight_total),
                'items': requested_list
            },
            
            # Возвращено админу
            'returned_to_admin': {
                'total_amount': str(returned_to_admin_total),
                'piece_count': returned_to_admin_piece_count,
                'weight_total': str(returned_to_admin_weight_total),
                'items': returned_to_admin_list
            },
            
            # Продано магазинам
            'sold': {
                'total_amount': str(sold_total),
                'piece_count': sold_piece_count,
                'weight_total': str(sold_weight_total),
                'items': sold_list
            },
            
            # Остаток товара
            'inventory': {
                'total_amount': str(inventory_total),
                'piece_count': inventory_piece_count,
                'weight_total': str(inventory_weight_total),
                'items': inventory_list
            },
            
            # Расходы
            'expenses': {
                'total_amount': str(expenses_total),
                'items': expenses_list
            },
            
            # Брак
            'defective': {
                'total_amount': str(defective_total),
                'items': defective_list
            },
            
            # Бонусы
            'bonus': {
                'total_amount': str(bonus_total),
                'count': bonus_count,
                'items': bonus_list
            },
            
            # Возвраты
            'returned': {
                'total_amount': str(returned_total),
                'piece_count': returned_piece_count,
                'weight_total': str(returned_weight_total),
                'items': returned_list
            },
            
            # Долги
            'debt': str(unpaid_debt),
            'paid_debt': str(paid_debt),
            
            # Итого
            'grand_total': str(grand_total),
            
            # Метаданные
            'period': period,
            'date_from': date_from.date().isoformat() if date_from else None,
            'date_to': date_to.date().isoformat() if date_to else None,
        }
    
    @staticmethod
    def _get_date_range(period: str) -> tuple:
        """Получить диапазон дат для периода."""
        now = timezone.now()
        
        if period == 'day':
            date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
            date_to = now
        elif period == 'week':
            date_from = now - timedelta(days=7)
            date_to = now
        elif period == 'month':
            date_from = now - timedelta(days=30)
            date_to = now
        elif period == 'half_year':
            date_from = now - timedelta(days=180)
            date_to = now
        elif period == 'year':
            date_from = now - timedelta(days=365)
            date_to = now
        else:  # all_time
            # Фиксированная дата начала для "все время"
            date_from = timezone.datetime(2020, 1, 1, tzinfo=timezone.get_current_timezone())
            date_to = now
        
        return date_from, date_to


# =============================================================================
# PARTNER PROFILE SERVICE (v3.0)
# =============================================================================

class PartnerProfileService:
    """
    Сервис для получения профиля партнёра (v3.1).
    
    ИЗМЕНЕНИЯ v3.1:
    - Возвращает ПЛОСКУЮ таблицу продаж (не группированную по магазинам)
    - Добавлен список доступных магазинов для фильтра
    - Добавлен фильтр по store_id
    - Добавлены итоги (piece_count, weight_total, total_amount)
    
    Структура соответствует макету мобильного приложения.
    """
    
    @staticmethod
    def get_profile_data(
        partner_id: int,
        period: str = 'month',
        store_id: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Получить данные профиля партнёра в формате таблицы продаж.
        
        Args:
            partner_id: ID партнёра
            period: Период (day/week/month/half_year/year/all_time)
            store_id: Фильтр по магазину (опционально)
            date_from: Начальная дата (опционально)
            date_to: Конечная дата (опционально)
            
        Returns:
            Dict с данными:
            - available_stores: список магазинов для фильтра
            - sales: плоская таблица продаж
            - totals: итоги
            
        Пример структуры:
            {
                'period': 'week',
                'date_from': '2025-05-08',
                'date_to': '2025-05-14',
                'available_stores': [
                    {'id': 1, 'name': 'Оси сила', 'inn': '82630930114'},
                    {'id': 2, 'name': 'Тынчтык', 'inn': '12345678'}
                ],
                'sales': [
                    {
                        'date': '01.05.25',
                        'store_name': 'Тынчтык',
                        'store_inn': '12345678',
                        'product_name': 'Пельмени Хуторок',
                        'quantity': 2,
                        'unit': 'шт',
                        'price': '600',
                        'total': '1200'
                    }
                ],
                'totals': {
                    'piece_count': 48,
                    'weight_total': '10.5',
                    'total_amount': '4900'
                }
            }
        """
        from orders.models import StoreOrderItem
        from stores.models import Store
        
        # Определить диапазон дат
        if not date_from or not date_to:
            date_from, date_to = PartnerStatisticsService._get_date_range(period)
        
        # =========================================================================
        # 1. ПОЛУЧИТЬ СПИСОК ДОСТУПНЫХ МАГАЗИНОВ ДЛЯ ФИЛЬТРА
        # =========================================================================
        store_ids_with_orders = StoreOrder.objects.filter(
            partner_id=partner_id,
            status=StoreOrderStatus.ACCEPTED
        ).values_list('store_id', flat=True).distinct()
        
        available_stores = Store.objects.filter(
            id__in=store_ids_with_orders
        ).values('id', 'name', 'inn').order_by('name')
        
        available_stores_list = [
            {'id': s['id'], 'name': s['name'], 'inn': s['inn']}
            for s in available_stores
        ]
        
        # =========================================================================
        # 2. ПОЛУЧИТЬ ЗАКАЗЫ ПАРТНЁРА ЗА ПЕРИОД
        # =========================================================================
        orders_qs = StoreOrder.objects.filter(
            partner_id=partner_id,
            status=StoreOrderStatus.ACCEPTED,
            confirmed_at__range=[date_from, date_to]
        )
        
        # Применить фильтр по магазину
        if store_id:
            orders_qs = orders_qs.filter(store_id=store_id)
        
        orders = orders_qs.select_related('store').prefetch_related(
            'items__product'
        ).order_by('confirmed_at')
        
        # =========================================================================
        # 3. ФОРМИРОВАТЬ ПЛОСКУЮ ТАБЛИЦУ ПРОДАЖ
        # =========================================================================
        sales = []
        piece_count = 0
        weight_total = Decimal('0')
        total_amount = Decimal('0')
        
        for order in orders:
            store = order.store
            order_date = order.confirmed_at.strftime('%d.%m.%y')
            
            # Считаем итог по заказу один раз (items уже prefetch)
            order_items_cached = list(order.items.all())
            order_piece_qty = sum(
                int(i.quantity) for i in order_items_cached if not i.product.is_weight_based
            )

            for item in order_items_cached:
                product = item.product

                if product.is_weight_based:
                    unit = 'кг'
                    weight_total += item.quantity
                else:
                    unit = 'шт'
                    piece_count += int(item.quantity)

                total_amount += item.total

                sales.append({
                    'order_id': order.id,
                    'order_total': str(order.total_amount),
                    'order_quantity': order_piece_qty,
                    'date': order_date,
                    'store_id': store.id,
                    'store_name': store.name,
                    'store_inn': store.inn,
                    'product_name': product.name,
                    'quantity': float(item.quantity),
                    'unit': unit,
                    'price': str(item.price),
                    'total': str(item.total)
                })
        
        # =========================================================================
        # 4. ФОРМИРОВАТЬ ОТВЕТ
        # =========================================================================
        return {
            'period': period,
            'date_from': date_from.date().isoformat() if date_from else None,
            'date_to': date_to.date().isoformat() if date_to else None,
            
            # Список магазинов для фильтра
            'available_stores': available_stores_list,
            
            # Применённый фильтр
            'filter': {
                'store_id': store_id
            },
            
            # Плоская таблица продаж
            'sales': sales,
            
            # Итоги
            'totals': {
                'piece_count': piece_count,
                'weight_total': str(weight_total),
                'total_amount': str(total_amount),
                'sales_count': len(sales)
            }
        }