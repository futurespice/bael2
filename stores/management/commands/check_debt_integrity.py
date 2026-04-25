"""
Проверка целостности долгов магазинов.

Для каждого магазина сравнивает Store.debt (источник правды) с формулой,
по которой считают эндпоинты статистики (PartnerDebtViewSet и т.д.):

    formula = Σ(total_amount) − Σ(prepayment_amount) − Σ(DebtPayment.amount)
              для ACCEPTED заказов магазина (включая прямые платежи order=None)

Если formula ≠ Store.debt — выводит расхождение. Это сигнал, что какой-то
скрипт/процесс рассинхронизировал данные.

Использование:
    python manage.py check_debt_integrity              # вывести только расхождения
    python manage.py check_debt_integrity --all        # вывести все магазины
    python manage.py check_debt_integrity --tolerance 1  # допуск ±1 сом
    python manage.py check_debt_integrity --json       # JSON-вывод (для cron/Slack)
"""
import json
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum

from orders.models import DebtPayment, StoreOrder, StoreOrderStatus
from stores.models import Store


class Command(BaseCommand):
    help = 'Проверка целостности Store.debt относительно формулы по заказам и платежам'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Вывести все магазины, а не только расхождения',
        )
        parser.add_argument(
            '--tolerance',
            type=str,
            default='0.01',
            help='Допустимое расхождение в сомах (по умолчанию 0.01)',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Вывод в JSON (для cron/Slack/мониторинга)',
        )

    def handle(self, *args, **options):
        show_all = options['all']
        tolerance = Decimal(options['tolerance'])
        as_json = options['json']

        results = []
        drift_count = 0
        ok_count = 0

        for store in Store.objects.filter(is_active=True).order_by('name'):
            agg = StoreOrder.objects.filter(
                store=store, status=StoreOrderStatus.ACCEPTED
            ).aggregate(
                t=Sum('total_amount'),
                p=Sum('prepayment_amount'),
            )
            total = agg['t'] or Decimal('0')
            prepay = agg['p'] or Decimal('0')

            paid = DebtPayment.objects.filter(
                Q(order__store=store, order__status=StoreOrderStatus.ACCEPTED)
                | Q(order__isnull=True, store=store)
            ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

            formula = (total - prepay - paid).quantize(Decimal('0.01'))
            store_debt = store.debt
            diff = (formula - store_debt).quantize(Decimal('0.01'))

            is_drift = abs(diff) > tolerance
            if is_drift:
                drift_count += 1
            else:
                ok_count += 1

            if is_drift or show_all:
                results.append({
                    'store_id': store.id,
                    'store_name': store.name,
                    'store_debt': str(store_debt),
                    'formula': str(formula),
                    'diff': str(diff),
                    'drift': is_drift,
                })

        if as_json:
            self.stdout.write(json.dumps({
                'ok_count': ok_count,
                'drift_count': drift_count,
                'tolerance': str(tolerance),
                'results': results,
            }, ensure_ascii=False, indent=2))
            return

        # Текстовый вывод
        self.stdout.write('=' * 78)
        self.stdout.write('ПРОВЕРКА ЦЕЛОСТНОСТИ ДОЛГОВ МАГАЗИНОВ')
        self.stdout.write('=' * 78)
        self.stdout.write(
            f'Допуск: ±{tolerance} сом   |   '
            f'OK: {ok_count}   |   Расхождений: {drift_count}'
        )
        self.stdout.write('=' * 78)

        if not results:
            self.stdout.write(self.style.SUCCESS(
                '\n✓ Все магазины консистентны (Store.debt совпадает с формулой).'
            ))
            return

        # Шапка таблицы
        self.stdout.write(
            f"\n{'ID':>5}  {'Магазин':<40}  {'Store.debt':>12}  "
            f"{'Формула':>12}  {'Разница':>10}"
        )
        self.stdout.write('─' * 87)

        for r in results:
            line = (
                f"{r['store_id']:>5}  {r['store_name'][:40]:<40}  "
                f"{r['store_debt']:>12}  {r['formula']:>12}  {r['diff']:>10}"
            )
            if r['drift']:
                self.stdout.write(self.style.ERROR(line))
            else:
                self.stdout.write(line)

        self.stdout.write('\n' + '=' * 78)
        if drift_count > 0:
            self.stdout.write(self.style.ERROR(
                f'⚠ Найдено {drift_count} расхождений. '
                f'Возможно, нужен повторный запуск scripts/backfill_phantom_debt.py '
                f'или ручная корректировка.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('✓ Расхождений нет.'))
        self.stdout.write('=' * 78)
