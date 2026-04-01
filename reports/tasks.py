# apps/reports/tasks.py
"""
Celery задачи для отчётов (v2.1).

Задачи для генерации ежедневной статистики.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from celery import shared_task
from django.db import transaction, IntegrityError
from django.db.models import Sum, Q, F, ExpressionWrapper, DecimalField as DField
from django.utils import timezone

logger = logging.getLogger(__name__)


def _upsert_daily_report(date, store, partner, region, city, defaults):
    """
    Идемпотентный upsert DailyReport.

    PostgreSQL разрешает несколько NULL-строк в UNIQUE constraint
    (NULL != NULL по стандарту SQL), поэтому стандартный update_or_create
    может создавать дубликаты при параллельных Celery-воркерах.

    Алгоритм: UPDATE → CREATE (savepoint) → при IntegrityError повторный UPDATE.
    Весь вызов находится внутри внешнего @transaction.atomic задачи.
    """
    from .models import DailyReport

    # Фильтр с IS NULL для None-значений — PostgreSQL корректно находит строку
    filter_kwargs = {'date': date}
    create_kwargs = {'date': date}
    for field, value in [('store', store), ('partner', partner),
                          ('region', region), ('city', city)]:
        if value is None:
            filter_kwargs[f'{field}__isnull'] = True
        else:
            filter_kwargs[field] = value
        create_kwargs[field] = value

    updated = DailyReport.objects.filter(**filter_kwargs).update(**defaults)
    if not updated:
        try:
            # savepoint: IntegrityError не откатит внешнюю транзакцию
            with transaction.atomic():
                DailyReport.objects.create(**create_kwargs, **defaults)
        except IntegrityError:
            # Параллельный воркер вставил запись первым — обновляем
            DailyReport.objects.filter(**filter_kwargs).update(**defaults)


@shared_task
@transaction.atomic
def generate_daily_report(report_date: str = None):
    """
    Генерация ежедневного отчёта.

    Собирает статистику за день и сохраняет в DailyReport.

    Args:
        report_date: Дата в формате 'YYYY-MM-DD', по умолчанию вчера
    """
    from .models import DailyReport
    from orders.models import StoreOrder, StoreOrderStatus, StoreOrderItem, DefectiveProduct, DebtPayment
    from products.models import PartnerExpense
    from stores.models import Store

    if report_date:
        target_date = date.fromisoformat(report_date)
    else:
        # localdate() возвращает дату в TIME_ZONE (Asia/Bishkek, UTC+6).
        # timezone.now().date() давало бы UTC-дату, что смещает отчёт на -1 день
        # в окне 00:00–06:00 Bishkek (18:00–24:00 UTC).
        target_date = timezone.localdate() - timedelta(days=1)

    logger.info(f"Генерация отчёта за {target_date}")

    # Один запрос: все ACCEPTED заказы за день с prefetch
    all_day_orders = (
        StoreOrder.objects
        .filter(confirmed_at__date=target_date, status=StoreOrderStatus.ACCEPTED)
        .select_related('store')
        .prefetch_related('items')
    )

    # Агрегаты по всем заказам дня одним запросом.
    # paid_amount не используем: pay_store_debt не обновляет StoreOrder.paid_amount,
    # поэтому paid_debt считаем через DebtPayment ниже (как в ReportService).
    all_day_agg = all_day_orders.aggregate(
        total_income=Sum('total_amount'),
        total_prepayment=Sum('prepayment_amount'),
        total_debt=Sum('debt_amount'),
    )

    # Бонусы по всем заказам дня одним запросом (количество и стоимость)
    all_day_bonus = (
        StoreOrderItem.objects
        .filter(order__confirmed_at__date=target_date,
                order__status=StoreOrderStatus.ACCEPTED,
                is_bonus=True)
        .aggregate(
            total_qty=Sum('quantity'),
            total_amount=Sum(ExpressionWrapper(
                F('price') * F('quantity'),
                output_field=DField(max_digits=14, decimal_places=2)
            ))
        )
    )

    # Брак по всем заказам дня одним запросом.
    # Используем order__confirmed_at для консистентности с reports/services.py:
    # дефект привязывается к дню подтверждения заказа, а не дню регистрации брака.
    all_day_defects = (
        DefectiveProduct.objects
        .filter(order__confirmed_at__date=target_date,
                status=DefectiveProduct.DefectStatus.APPROVED)
        .aggregate(total=Sum('total_amount'))
    )

    # Собираем данные по каждому магазину
    stores = Store.objects.filter(is_active=True)

    for store in stores:
        store_orders = [o for o in all_day_orders if o.store_id == store.pk]

        if not store_orders:
            continue

        order_ids = [o.pk for o in store_orders]

        # Агрегаты по магазину
        income = sum(o.total_amount for o in store_orders)
        debt = sum(o.debt_amount for o in store_orders)
        orders_count = len(store_orders)

        # paid_debt: предоплата + погашения за этот день (через DebtPayment).
        # Методология совпадает с ReportService.calculate_statistics для согласованности.
        prepayment = sum(o.prepayment_amount for o in store_orders)
        day_payments = (
            DebtPayment.objects
            .filter(order_id__in=order_ids, created_at__date=target_date)
            .aggregate(total=Sum('amount'))['total'] or Decimal('0')
        )
        paid_debt = prepayment + day_payments

        # Бонусы по магазину (количество и финансовая стоимость)
        bonus_agg = (
            StoreOrderItem.objects
            .filter(order_id__in=order_ids, is_bonus=True)
            .aggregate(
                total_qty=Sum('quantity'),
                total_amount=Sum(ExpressionWrapper(
                    F('price') * F('quantity'),
                    output_field=DField(max_digits=14, decimal_places=2)
                ))
            )
        )
        bonus_count = int(bonus_agg['total_qty'] or 0)
        bonus_amount = bonus_agg['total_amount'] or Decimal('0')

        # Брак по магазину — по дате подтверждения заказа (консистентно с reports/services.py)
        defect_amount = (
            DefectiveProduct.objects
            .filter(order_id__in=order_ids,
                    order__confirmed_at__date=target_date,
                    status=DefectiveProduct.DefectStatus.APPROVED)
            .aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        )

        _upsert_daily_report(
            date=target_date,
            store=store,
            partner=None,
            region=store.region,
            city=store.city,
            defaults={
                'income': income,
                'debt': debt,
                'paid_debt': paid_debt,
                'bonus_count': bonus_count,
                'bonus_amount': bonus_amount,
                'defect_amount': defect_amount,
                'orders_count': orders_count,
            }
        )

    # Общий отчёт по расходам партнёров
    expenses = PartnerExpense.objects.filter(date=target_date)
    total_expenses = (
        expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    )

    # Общий отчёт (без привязки к магазину) — из уже загруженных данных
    total_income = all_day_agg['total_income'] or Decimal('0')
    total_debt = all_day_agg['total_debt'] or Decimal('0')
    total_prepayment = all_day_agg['total_prepayment'] or Decimal('0')
    global_day_payments = (
        DebtPayment.objects
        .filter(created_at__date=target_date)
        .aggregate(total=Sum('amount'))['total'] or Decimal('0')
    )
    total_paid_debt = total_prepayment + global_day_payments
    total_bonus_count = int(all_day_bonus['total_qty'] or 0)
    total_bonus_amount = all_day_bonus['total_amount'] or Decimal('0')
    total_defect_amount = all_day_defects['total'] or Decimal('0')
    total_orders_count = all_day_orders.count()

    _upsert_daily_report(
        date=target_date,
        store=None,
        partner=None,
        region=None,
        city=None,
        defaults={
            'income': total_income,
            'debt': total_debt,
            'paid_debt': total_paid_debt,
            'bonus_count': total_bonus_count,
            'bonus_amount': total_bonus_amount,
            'defect_amount': total_defect_amount,
            'expenses': total_expenses,
            'orders_count': total_orders_count,
        }
    )

    logger.info(f"Отчёт за {target_date} сгенерирован")
    return {'date': str(target_date), 'stores_processed': stores.count()}


@shared_task
def cleanup_old_reports(days: int = 365):
    """
    Удаление старых отчётов (старше года).

    Args:
        days: Сколько дней хранить отчёты
    """
    from .models import DailyReport

    threshold = timezone.localdate() - timedelta(days=days)

    deleted, _ = DailyReport.objects.filter(date__lt=threshold).delete()

    logger.info(f"Удалено {deleted} старых отчётов")
    return {'deleted': deleted}
