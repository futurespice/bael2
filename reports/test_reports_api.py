"""
Тесты API отчётов и статистики БайЭл.

Покрывает:
  1. GET /api/reports/statistics/               — статистика (admin)
  2. GET /api/reports/store-history/{store_id}/ — история магазина
  3. GET /api/reports/partners/statistics/      — статистика партнёра
  4. GET /api/reports/partners/profile/         — профиль партнёра

НЕ тестируется (по требованию):
  - GET /api/reports/partners/tracker/

ДАННЫЕ ТЕСТА (описание сценария):
  - 2 ACCEPTED заказа магазина:
      order1: total=1500, prepayment=300, debt=1200
        items: 10 мороженых × 100 (обычные) + 5 × 100 (бонусные, total=0)
        DebtPayment: 500 сом
        APPROVED DefectiveProduct: 2 шт × 100 = 200 сом
      order2: total=800, prepayment=100, debt=700
        items: 8 соков × 100
  - PartnerExpense: 600 сом
  - PartnerInventory: 90 мороженых, 92 соков

ОЖИДАЕМЫЕ ЦИФРЫ (all_time / year, без накладных расходов):
  AdminStatistics:
    income          = 1500 + 800 = 2300
    prepayment      = 300 + 100 = 400
    debt_payments   = 500
    paid_debt       = 400 + 500 = 900
    original_debt   = 1200 + 700 = 1900
    debt            = 1900 - 500(payments) - 200(defects) = 1200
    defect_amount   = 200
    partner_expenses= 600
    production_exp  = 0 (нет overhead Expense в тесте)
    total_expenses  = 600
    orders_count    = 2
    products_count  = 10 + 8 = 18 (без бонусов)
    bonus_count     = 5
    profit          = 2300 - 200 - 600 = 1500
    total_balance   = 2300 - 200 - 600 - 1200 = 300

  StoreHistory:
    total_amount   = 2300
    total_debt     = (1200 + 700) - defect(200) = 1700
    total_prepayment = 400
    total_paid_debt = 500
    remaining_debt = 1700 - 500 = 1200

  PartnerStatistics (sold excludes bonuses):
    sold.total_amount = 1000 (10 ice_cream) + 800 (8 juice) = 1800
    sold.piece_count  = 18
    bonus.count       = 5
    bonus.total_amount = 5 × 100 = 500
    defective.total_amount = 200
    expenses.total_amount  = 600
    grand_total        = paid_debt(900) - expenses(600) - bonus(500) = -200
    debt               = str, > 0

  PartnerProfile (flat sales table, all items including bonus):
    sales: 3 строки (2 позиции order1 + 1 order2)
    totals.piece_count  = 10 + 5 + 8 = 23
    totals.total_amount = 1000 + 0 + 800 = 1800 (bonus has total=0)
    totals.sales_count  = 3
    available_stores: [Тест Магазин Отчёт]
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from orders.models import (
    StoreOrder, StoreOrderItem, StoreOrderStatus, StoreOrderType,
    DebtPayment, DefectiveProduct,
)
from products.models import Product, PartnerExpense
from stores.models import Store, Region, City, PartnerInventory
from users.models import User


# =============================================================================
# Общий setUp для всех тестов отчётов
# =============================================================================

class ReportsBaseTest(TestCase):
    """Создаёт полный набор данных, используемый всеми тестами статистики."""

    def setUp(self):
        self.client = APIClient()

        # --- Пользователи ---
        self.admin = User.objects.create(
            phone='+996700100001', email='r_admin@test.local',
            name='Админ', second_name='Тест', role='admin',
            is_staff=True, is_superuser=True, is_active=True,
        )
        self.admin.set_password('admin123')
        self.admin.save()

        self.partner = User.objects.create(
            phone='+996700100002', email='r_partner@test.local',
            name='Партнёр', second_name='Тест', role='partner', is_active=True,
        )
        self.partner.set_password('partner123')
        self.partner.save()

        self.store_owner = User.objects.create(
            phone='+996700100003', email='r_store@test.local',
            name='Магазин', second_name='Тест', role='store', is_active=True,
        )
        self.store_owner.set_password('store123')
        self.store_owner.save()

        # --- География ---
        self.region = Region.objects.create(name='Тест Регион Отчёт')
        self.city = City.objects.create(name='Тест Город Отчёт', region=self.region)

        # --- Магазин ---
        self.store = Store.objects.create(
            name='Тест Магазин Отчёт',
            owner=self.store_owner,
            region=self.region,
            city=self.city,
            address='ул. Тестовая, 99',
            inn='999000100001',
            owner_name='Отчёт ТЕСТ',
            phone='+996555100001',
            approval_status='approved',
            is_active=True,
        )

        # --- Товары ---
        self.ice_cream = Product.objects.create(
            name='Тест Мороженое Отчёт',
            manual_price=Decimal('100.00'),
            stock_quantity=Decimal('1000'),
            is_available=True,
            is_weight_based=False,
            is_bonus=True,
        )
        self.juice = Product.objects.create(
            name='Тест Сок Отчёт',
            manual_price=Decimal('100.00'),
            stock_quantity=Decimal('500'),
            is_available=True,
            is_weight_based=False,
            is_bonus=False,
        )

        # --- Инвентарь партнёра ---
        PartnerInventory.objects.create(
            partner=self.partner,
            product=self.ice_cream,
            quantity=Decimal('90'),
            reserved_quantity=Decimal('0'),
        )
        PartnerInventory.objects.create(
            partner=self.partner,
            product=self.juice,
            quantity=Decimal('92'),
            reserved_quantity=Decimal('0'),
        )

        today = timezone.now()

        # --- Заказ 1: 10 обычных + 5 бонусных мороженых ---
        self.order1 = StoreOrder.objects.create(
            store=self.store,
            partner=self.partner,
            created_by=self.store_owner,
            status=StoreOrderStatus.ACCEPTED,
            order_type=StoreOrderType.PREORDER,
            total_amount=Decimal('1500.00'),
            prepayment_amount=Decimal('300.00'),
            debt_amount=Decimal('1200.00'),
            paid_amount=Decimal('500.00'),
            confirmed_at=today,
            confirmed_by=self.partner,
        )
        StoreOrderItem.objects.create(
            order=self.order1,
            product=self.ice_cream,
            quantity=Decimal('10'),
            price=Decimal('100.00'),
            total=Decimal('1000.00'),
            is_bonus=False,
        )
        StoreOrderItem.objects.create(
            order=self.order1,
            product=self.ice_cream,
            quantity=Decimal('5'),
            price=Decimal('100.00'),
            total=Decimal('0.00'),
            is_bonus=True,
        )
        DebtPayment.objects.create(
            order=self.order1,
            store=self.order1.store,
            amount=Decimal('500.00'),
            comment='Частичная оплата',
            paid_by=self.store_owner,
            received_by=self.partner,
        )
        self.defect = DefectiveProduct.objects.create(
            order=self.order1,
            product=self.ice_cream,
            quantity=Decimal('2'),
            price=Decimal('100.00'),
            total_amount=Decimal('200.00'),
            status=DefectiveProduct.DefectStatus.APPROVED,
            reason='Повреждена упаковка',
            reported_by=self.partner,
            reviewed_by=self.admin,
        )

        # --- Заказ 2: 8 соков ---
        self.order2 = StoreOrder.objects.create(
            store=self.store,
            partner=self.partner,
            created_by=self.store_owner,
            status=StoreOrderStatus.ACCEPTED,
            order_type=StoreOrderType.PREORDER,
            total_amount=Decimal('800.00'),
            prepayment_amount=Decimal('100.00'),
            debt_amount=Decimal('700.00'),
            paid_amount=Decimal('0.00'),
            confirmed_at=today,
            confirmed_by=self.partner,
        )
        StoreOrderItem.objects.create(
            order=self.order2,
            product=self.juice,
            quantity=Decimal('8'),
            price=Decimal('100.00'),
            total=Decimal('800.00'),
            is_bonus=False,
        )

        # --- Расход партнёра ---
        PartnerExpense.objects.create(
            partner=self.partner,
            amount=Decimal('600.00'),
            description='Аренда склада тест',
            date=today.date(),
        )


# =============================================================================
# 1. GET /api/reports/statistics/
# =============================================================================

class AdminStatisticsTest(ReportsBaseTest):
    """Тесты эндпоинта GET /api/reports/statistics/"""

    URL = '/api/reports/statistics/'

    def _auth_admin(self):
        self.client.force_authenticate(user=self.admin)

    # --- Авторизация ---

    def test_requires_authentication(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_accessible_by_admin(self):
        self._auth_admin()
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_accessible_by_partner(self):
        self.client.force_authenticate(user=self.partner)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_accessible_by_store_user(self):
        self.client.force_authenticate(user=self.store_owner)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- Структура ответа ---

    def test_response_structure(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertIn('period', data)
        self.assertIn('filters', data)
        self.assertIn('statistics', data)
        self.assertIn('chart_data', data)

    def test_statistics_fields(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        stats = response.data['statistics']

        for field in [
            'income', 'debt', 'paid_debt', 'defect_amount',
            'partner_expenses', 'production_expenses', 'total_expenses',
            'bonus_count', 'orders_count', 'products_count', 'sold_total',
            'total_balance', 'profit',
        ]:
            self.assertIn(field, stats, msg=f'Поле {field!r} отсутствует в statistics')

    def test_chart_data_fields(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        chart = response.data['chart_data']
        for field in ['income', 'debt', 'defect', 'expenses']:
            self.assertIn(field, chart)

    # --- Значения (all_time) ---

    def test_income(self):
        """income = sum(total_amount) всех ACCEPTED заказов = 1500 + 800 = 2300"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(response.data['statistics']['income'], 2300.0)

    def test_orders_count(self):
        """orders_count = 2"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertEqual(response.data['statistics']['orders_count'], 2)

    def test_products_count(self):
        """products_count = qty проданных позиций (без бонусов) = 10 + 8 = 18"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertEqual(response.data['statistics']['products_count'], 18)

    def test_bonus_count(self):
        """bonus_count = qty бонусных позиций = 5"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertEqual(response.data['statistics']['bonus_count'], 5)

    def test_paid_debt(self):
        """paid_debt = prepayment(300+100) + DebtPayments(500) = 900"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(response.data['statistics']['paid_debt'], 900.0)

    def test_debt(self):
        """debt = original_debt(1900) - paid_via_payments(500) - defects(200) = 1200"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(response.data['statistics']['debt'], 1200.0)

    def test_defect_amount(self):
        """defect_amount = 200 (APPROVED дефект)"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(response.data['statistics']['defect_amount'], 200.0)

    def test_partner_expenses(self):
        """partner_expenses = 600 (PartnerExpense)"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(response.data['statistics']['partner_expenses'], 600.0)

    def test_profit(self):
        """profit = income - defect - total_expenses - bonus = 2300 - 200 - 600 - 500 = 1000"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(response.data['statistics']['profit'], 1000.0)

    def test_total_balance(self):
        """total_balance = income - defect - expenses - debt - bonus = 2300 - 200 - 600 - 1200 - 500 = -200"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(response.data['statistics']['total_balance'], -200.0)

    def test_pending_defect_not_counted(self):
        """PENDING дефект НЕ входит в defect_amount"""
        DefectiveProduct.objects.create(
            order=self.order2,
            product=self.juice,
            quantity=Decimal('1'),
            price=Decimal('100.00'),
            total_amount=Decimal('100.00'),
            status=DefectiveProduct.DefectStatus.PENDING,
            reason='Тест',
            reported_by=self.partner,
        )
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        # defect_amount всё ещё 200 (только APPROVED)
        self.assertAlmostEqual(response.data['statistics']['defect_amount'], 200.0)

    # --- Фильтр по магазину ---

    def test_filter_by_store(self):
        """Фильтр ?store_id=X — данные только по одному магазину"""
        self._auth_admin()
        response = self.client.get(self.URL, {
            'period': 'all_time',
            'store_id': self.store.id,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertAlmostEqual(response.data['statistics']['income'], 2300.0)

    def test_filter_by_nonexistent_store_returns_zeros(self):
        """Фильтр по несуществующему магазину → все нули"""
        self._auth_admin()
        response = self.client.get(self.URL, {
            'period': 'all_time',
            'store_id': 99999,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['statistics']['orders_count'], 0)
        self.assertAlmostEqual(response.data['statistics']['income'], 0.0)

    # --- Фильтр по партнёру ---

    def test_filter_by_partner(self):
        """Фильтр ?partner_id=X — доход только по заказам этого партнёра"""
        self._auth_admin()
        response = self.client.get(self.URL, {
            'period': 'all_time',
            'partner_id': self.partner.id,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertAlmostEqual(response.data['statistics']['income'], 2300.0)

    def test_filter_by_other_partner_returns_zeros(self):
        """Фильтр по другому партнёру (без заказов) → нули"""
        self._auth_admin()
        response = self.client.get(self.URL, {
            'period': 'all_time',
            'partner_id': self.admin.id,
        })
        self.assertEqual(response.data['statistics']['orders_count'], 0)

    # --- Фильтр по периоду ---

    def test_period_all_time_includes_all_orders(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertEqual(response.data['statistics']['orders_count'], 2)

    def test_period_day_includes_todays_orders(self):
        """period=day — заказы за сегодня попадают в статистику"""
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'day'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['statistics']['orders_count'], 2)

    def test_period_future_date_excludes_orders(self):
        """Диапазон дат в будущем → заказов нет"""
        self._auth_admin()
        future = (timezone.localdate() + timedelta(days=30)).isoformat()
        response = self.client.get(self.URL, {
            'period': 'all_time',
            'start_date': future,
            'end_date': future,
        })
        self.assertEqual(response.data['statistics']['orders_count'], 0)

    def test_invalid_period_returns_400(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'bad_value'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- chart_data ---

    def test_chart_data_income_matches_statistics(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(
            response.data['chart_data']['income'],
            response.data['statistics']['income'],
        )

    def test_chart_data_debt_matches_statistics(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'period': 'all_time'})
        self.assertAlmostEqual(
            response.data['chart_data']['debt'],
            response.data['statistics']['debt'],
        )


# =============================================================================
# 2. GET /api/reports/store-history/{store_id}/
# =============================================================================

class StoreHistoryTest(ReportsBaseTest):
    """Тесты эндпоинта GET /api/reports/store-history/{store_id}/"""

    def _url(self, store_id=None):
        sid = store_id or self.store.id
        return f'/api/reports/store-history/{sid}/'

    def _auth_admin(self):
        self.client.force_authenticate(user=self.admin)

    # --- Авторизация ---

    def test_requires_authentication(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_404_for_nonexistent_store(self):
        self._auth_admin()
        response = self.client.get(self._url(99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Структура ---

    def test_returns_list(self):
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_returns_entry_per_day(self):
        """Оба заказа за сегодня → 1 запись в истории"""
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertEqual(len(response.data), 1)

    def test_day_entry_fields(self):
        self._auth_admin()
        response = self.client.get(self._url())
        entry = response.data[0]
        for field in [
            'date', 'orders', 'products', 'bonus_products',
            'defective_products', 'debt_payments',
            'total_amount', 'total_debt', 'total_prepayment',
            'total_paid_debt', 'remaining_debt',
        ]:
            self.assertIn(field, entry, msg=f'Поле {field!r} отсутствует')

    # --- Суммы ---

    def test_total_amount(self):
        """total_amount = 1500 + 800 = 2300"""
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertAlmostEqual(response.data[0]['total_amount'], 2300.0)

    def test_total_prepayment(self):
        """total_prepayment = 300 + 100 = 400"""
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertAlmostEqual(response.data[0]['total_prepayment'], 400.0)

    def test_total_paid_debt(self):
        """total_paid_debt = DebtPayment(500)"""
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertAlmostEqual(response.data[0]['total_paid_debt'], 500.0)

    def test_total_debt_reduced_by_approved_defect(self):
        """total_debt = debt_amount(1200+700) - approved_defect(200) = 1700"""
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertAlmostEqual(response.data[0]['total_debt'], 1700.0)

    def test_remaining_debt(self):
        """remaining_debt = total_debt(1700) - paid_debt(500) = 1200"""
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertAlmostEqual(response.data[0]['remaining_debt'], 1200.0)

    # --- Список товаров ---

    def test_products_list(self):
        """products содержит обычные позиции (не бонусные)"""
        self._auth_admin()
        response = self.client.get(self._url())
        products = response.data[0]['products']
        names = [p['name'] for p in products]
        self.assertIn(self.ice_cream.name, names)
        self.assertIn(self.juice.name, names)

    def test_bonus_products_list(self):
        """bonus_products содержит бонусные позиции"""
        self._auth_admin()
        response = self.client.get(self._url())
        bonuses = response.data[0]['bonus_products']
        self.assertEqual(len(bonuses), 1)
        self.assertAlmostEqual(bonuses[0]['quantity'], 5.0)

    def test_defective_products_list(self):
        """defective_products содержит одобренный брак"""
        self._auth_admin()
        response = self.client.get(self._url())
        defects = response.data[0]['defective_products']
        self.assertEqual(len(defects), 1)
        self.assertAlmostEqual(defects[0]['quantity'], 2.0)
        self.assertAlmostEqual(defects[0]['amount'], 200.0)

    def test_debt_payments_list(self):
        """debt_payments содержит платежи"""
        self._auth_admin()
        response = self.client.get(self._url())
        payments = response.data[0]['debt_payments']
        self.assertEqual(len(payments), 1)
        self.assertAlmostEqual(payments[0]['amount'], 500.0)

    # --- Фильтрация по дате ---

    def test_future_date_filter_returns_empty(self):
        """Диапазон в будущем → пустой список"""
        self._auth_admin()
        future = (timezone.localdate() + timedelta(days=30)).isoformat()
        response = self.client.get(self._url(), {
            'start_date': future,
            'end_date': future,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_past_date_filter_returns_empty(self):
        """Диапазон до создания заказов → пустой список"""
        self._auth_admin()
        past = (timezone.localdate() - timedelta(days=365)).isoformat()
        response = self.client.get(self._url(), {
            'start_date': past,
            'end_date': past,
        })
        self.assertEqual(len(response.data), 0)

    def test_today_filter_returns_entry(self):
        """Фильтр на сегодня → 1 запись"""
        self._auth_admin()
        today = timezone.localdate().isoformat()
        response = self.client.get(self._url(), {
            'start_date': today,
            'end_date': today,
        })
        self.assertEqual(len(response.data), 1)

    def test_no_dates_returns_all(self):
        """Без дат → вся история"""
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # --- Два дня ---

    def test_two_orders_on_different_days_give_two_entries(self):
        """Если заказы в разные дни → 2 записи в истории"""
        yesterday = timezone.now() - timedelta(days=1)
        order3 = StoreOrder.objects.create(
            store=self.store,
            partner=self.partner,
            created_by=self.store_owner,
            status=StoreOrderStatus.ACCEPTED,
            order_type=StoreOrderType.PREORDER,
            total_amount=Decimal('200.00'),
            prepayment_amount=Decimal('0.00'),
            debt_amount=Decimal('200.00'),
            paid_amount=Decimal('0.00'),
            confirmed_at=yesterday,
            confirmed_by=self.partner,
        )
        StoreOrderItem.objects.create(
            order=order3,
            product=self.juice,
            quantity=Decimal('2'),
            price=Decimal('100.00'),
            total=Decimal('200.00'),
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self._url())
        self.assertEqual(len(response.data), 2)


# =============================================================================
# 3. GET /api/reports/partners/statistics/
# =============================================================================

class PartnerStatisticsAPITest(ReportsBaseTest):
    """Тесты GET /api/reports/partners/statistics/"""

    URL = '/api/reports/partners/statistics/'

    def _auth_partner(self):
        self.client.force_authenticate(user=self.partner)

    # --- Авторизация ---

    def test_requires_authentication(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_store_user_forbidden(self):
        """Пользователь с ролью store не имеет доступа"""
        self.client.force_authenticate(user=self.store_owner)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_forbidden(self):
        """Admin не имеет доступа к статистике партнёра"""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_partner_has_access(self):
        self._auth_partner()
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- Структура ответа ---

    def test_response_keys_present(self):
        """Проверяем ключи верхнего уровня"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        data = response.data
        for key in ['sold', 'inventory', 'expenses', 'defective', 'bonus', 'debt', 'paid_debt', 'sold_total']:
            self.assertIn(key, data, msg=f'Ключ {key!r} отсутствует в ответе')

    # --- Продажи (sold) ---

    def test_sold_total_amount(self):
        """sold.total_amount = только НЕ-бонусные позиции = 1000 + 800 = 1800"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sold = response.data['sold']
        self.assertAlmostEqual(float(sold['total_amount']), 1800.0, places=1)

    def test_sold_piece_count(self):
        """sold.piece_count = 10 + 8 = 18 (без бонусных)"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        sold = response.data['sold']
        self.assertIn('piece_count', sold)
        self.assertEqual(sold['piece_count'], 18)

    def test_sold_items_list(self):
        """sold.items содержит список проданных товаров"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        sold = response.data['sold']
        self.assertIn('items', sold)
        self.assertIsInstance(sold['items'], list)
        self.assertGreater(len(sold['items']), 0)

    # --- Инвентарь (inventory) ---

    def test_inventory_piece_count(self):
        """inventory.piece_count = 90 + 92 = 182"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        inv = response.data['inventory']
        self.assertIn('piece_count', inv)
        self.assertEqual(inv['piece_count'], 182)

    # --- Долг (debt) ---

    def test_debt_is_string_value(self):
        """debt — строковое представление числа >= 0"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        debt = response.data['debt']
        self.assertIsInstance(debt, str)
        self.assertGreaterEqual(float(debt), 0.0)

    # --- Брак (defective) ---

    def test_defective_total_amount(self):
        """defective.total_amount = сумма APPROVED дефектов = 200"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        defective = response.data['defective']
        self.assertAlmostEqual(float(defective['total_amount']), 200.0, places=1)

    # --- Бонус (bonus) ---

    def test_bonus_count(self):
        """bonus.count = 5 (бонусные позиции в заказах)"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        bonus = response.data['bonus']
        self.assertEqual(bonus['count'], 5)

    def test_bonus_total_amount(self):
        """bonus.total_amount = quantity × price = 5 × 100 = 500"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        bonus = response.data['bonus']
        self.assertAlmostEqual(float(bonus['total_amount']), 500.0, places=1)

    # --- Итого (grand_total) ---

    def test_grand_total(self):
        """grand_total = paid_debt(900) - expenses(600) = 300
        paid_debt = prepayment(300+100) + DebtPayment(500) = 900
        Бонусы НЕ вычитаются из grand_total.
        """
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        self.assertAlmostEqual(float(response.data['grand_total']), 300.0, places=1)

    # --- Расходы (expenses) ---

    def test_expenses_total_amount(self):
        """expenses.total_amount = PartnerExpense = 600"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        expenses = response.data['expenses']
        self.assertAlmostEqual(float(expenses['total_amount']), 600.0, places=1)

    # --- Периоды ---

    def test_period_day(self):
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'day'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_period_month(self):
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'month'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_invalid_period(self):
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'bad'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_specific_date_filter(self):
        """Конкретная дата ?date=YYYY-MM-DD"""
        self._auth_partner()
        today = timezone.localdate().isoformat()
        response = self.client.get(self.URL, {'date': today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_date_range_filter(self):
        """Диапазон ?date_from=... &date_to=..."""
        self._auth_partner()
        today = timezone.localdate().isoformat()
        response = self.client.get(self.URL, {
            'date_from': today,
            'date_to': today,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_future_period_returns_zeros(self):
        """Диапазон в будущем → sold.total_amount = 0"""
        self._auth_partner()
        future = (timezone.localdate() + timedelta(days=30)).isoformat()
        response = self.client.get(self.URL, {
            'date_from': future,
            'date_to': future,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sold = response.data['sold']
        self.assertAlmostEqual(float(sold['total_amount']), 0.0, places=1)


# =============================================================================
# 4. GET /api/reports/partners/profile/
# =============================================================================

class PartnerProfileAPITest(ReportsBaseTest):
    """
    Тесты GET /api/reports/partners/profile/

    Ответ v3.1 (плоская таблица продаж):
    {
        "period": "year",
        "date_from": "...",
        "date_to": "...",
        "available_stores": [{"id": ..., "name": "...", "inn": "..."}],
        "filter": {"store_id": null},
        "sales": [
            {"date": "...", "store_id": ..., "store_name": "...", "store_inn": "...",
             "product_name": "...", "quantity": ..., "unit": "шт", "price": "...", "total": "..."}
        ],
        "totals": {"piece_count": ..., "weight_total": "...", "total_amount": "...", "sales_count": ...}
    }
    """

    URL = '/api/reports/partners/profile/'

    def _auth_partner(self):
        self.client.force_authenticate(user=self.partner)

    # --- Авторизация ---

    def test_requires_authentication(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_store_user_forbidden(self):
        self.client.force_authenticate(user=self.store_owner)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_forbidden(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_partner_has_access(self):
        self._auth_partner()
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- Структура ответа ---

    def test_response_keys(self):
        """Проверяем ключи верхнего уровня"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        data = response.data
        for key in ['period', 'date_from', 'date_to', 'available_stores', 'filter', 'sales', 'totals']:
            self.assertIn(key, data, msg=f'Ключ {key!r} отсутствует')

    def test_available_stores_is_list(self):
        """available_stores — список"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        self.assertIsInstance(response.data['available_stores'], list)

    def test_available_store_entry_fields(self):
        """Каждый элемент available_stores имеет id, name, inn"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        stores = response.data['available_stores']
        self.assertGreater(len(stores), 0)
        store_entry = stores[0]
        for field in ['id', 'name', 'inn']:
            self.assertIn(field, store_entry, msg=f'Поле {field!r} отсутствует в available_stores')

    def test_available_store_name_and_inn(self):
        """Имя и INN магазина в available_stores совпадают с реальными данными"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        stores = response.data['available_stores']
        names = [s['name'] for s in stores]
        self.assertIn(self.store.name, names)
        store_entry = next(s for s in stores if s['name'] == self.store.name)
        self.assertEqual(store_entry['inn'], self.store.inn)

    def test_sales_is_list(self):
        """sales — список строк продаж"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        self.assertIsInstance(response.data['sales'], list)

    def test_sale_entry_fields(self):
        """Каждая запись в sales имеет необходимые поля"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        sales = response.data['sales']
        self.assertGreater(len(sales), 0)
        entry = sales[0]
        for field in ['date', 'store_id', 'store_name', 'store_inn', 'product_name', 'quantity', 'unit', 'price', 'total']:
            self.assertIn(field, entry, msg=f'Поле {field!r} отсутствует в sale entry')

    def test_totals_fields(self):
        """totals содержит piece_count, weight_total, total_amount, sales_count"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        totals = response.data['totals']
        for field in ['piece_count', 'weight_total', 'total_amount', 'sales_count']:
            self.assertIn(field, totals, msg=f'Поле {field!r} отсутствует в totals')

    # --- Суммы ---

    def test_totals_piece_count(self):
        """totals.piece_count = 10 + 5 + 8 = 23 (все позиции, включая бонусные)"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        totals = response.data['totals']
        self.assertEqual(totals['piece_count'], 23)

    def test_totals_total_amount(self):
        """totals.total_amount = 1000 + 0 (bonus) + 800 = 1800"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        totals = response.data['totals']
        self.assertAlmostEqual(float(totals['total_amount']), 1800.0, places=1)

    def test_totals_sales_count(self):
        """totals.sales_count = 3 (2 позиции order1 + 1 позиция order2)"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        totals = response.data['totals']
        self.assertEqual(totals['sales_count'], 3)

    def test_sales_store_matches(self):
        """Все записи в sales принадлежат тестовому магазину"""
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'year'})
        for sale in response.data['sales']:
            self.assertEqual(sale['store_name'], self.store.name)

    # --- Фильтры ---

    def test_filter_by_store_id(self):
        """?store_id= фильтрует sales по конкретному магазину"""
        self._auth_partner()
        response = self.client.get(self.URL, {
            'period': 'year',
            'store_id': self.store.id,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Все продажи принадлежат тестовому магазину
        for sale in response.data['sales']:
            self.assertEqual(sale['store_id'], self.store.id)

    def test_filter_by_wrong_store_id_returns_empty_sales(self):
        """Неправильный store_id → пустой sales"""
        self._auth_partner()
        response = self.client.get(self.URL, {
            'period': 'year',
            'store_id': 99999,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['sales']), 0)

    def test_filter_store_id_in_filter_key(self):
        """filter.store_id отражает применённый фильтр"""
        self._auth_partner()
        response = self.client.get(self.URL, {
            'period': 'year',
            'store_id': self.store.id,
        })
        self.assertEqual(response.data['filter']['store_id'], self.store.id)

    def test_period_day(self):
        self._auth_partner()
        response = self.client.get(self.URL, {'period': 'day'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_specific_date_filter(self):
        self._auth_partner()
        today = timezone.localdate().isoformat()
        response = self.client.get(self.URL, {'date': today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_future_date_returns_empty_sales(self):
        """Дата в будущем → sales пустой, totals.total_amount = 0"""
        self._auth_partner()
        future = (timezone.localdate() + timedelta(days=30)).isoformat()
        response = self.client.get(self.URL, {'date': future})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['sales']), 0)
        self.assertAlmostEqual(float(response.data['totals']['total_amount']), 0.0)

    def test_invalid_date_format_returns_400(self):
        """Неверный формат даты → 400"""
        self._auth_partner()
        response = self.client.get(self.URL, {'date': '01-13-2026'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# =============================================================================
# 5. GET /api/reports/admin/partner-statistics/{pk}/
# =============================================================================

class AdminPartnerStatisticsViewTest(ReportsBaseTest):
    """Тесты GET /api/reports/admin/partner-statistics/{pk}/"""

    def _url(self, pk=None):
        pk = pk if pk is not None else self.partner.id
        return f'/api/reports/admin/partner-statistics/{pk}/'

    def _auth_admin(self):
        self.client.force_authenticate(user=self.admin)

    # --- Авторизация ---

    def test_requires_authentication(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_partner_forbidden(self):
        """Партнёр не имеет доступа к этому эндпоинту"""
        self.client.force_authenticate(user=self.partner)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_store_user_forbidden(self):
        self.client.force_authenticate(user=self.store_owner)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_has_access(self):
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_404_for_nonexistent_partner(self):
        self._auth_admin()
        response = self.client.get(self._url(pk=99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_404_for_non_partner_role(self):
        """pk существует, но роль не partner → 404"""
        self._auth_admin()
        response = self.client.get(self._url(pk=self.admin.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Структура ответа ---

    def test_response_contains_partner_name(self):
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertIn('partner_name', response.data)
        self.assertIn('partner_id', response.data)

    def test_partner_name_matches(self):
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertEqual(response.data['partner_id'], self.partner.id)
        self.assertEqual(response.data['partner_name'], self.partner.get_full_name())

    def test_response_keys_present(self):
        self._auth_admin()
        response = self.client.get(self._url(), {'date': timezone.localdate().isoformat()})
        data = response.data
        for key in ['sold', 'inventory', 'expenses', 'defective', 'bonus', 'debt', 'paid_debt', 'grand_total', 'sold_total']:
            self.assertIn(key, data, msg=f'Ключ {key!r} отсутствует')

    # --- Данные совпадают с данными партнёра ---

    def test_sold_total_amount(self):
        """sold.total_amount = 1800 (как у партнёра за год)"""
        self._auth_admin()
        response = self.client.get(self._url(), {'period': 'year'})
        self.assertAlmostEqual(float(response.data['sold']['total_amount']), 1800.0, places=1)

    def test_bonus_count(self):
        """bonus.count = 5"""
        self._auth_admin()
        response = self.client.get(self._url(), {'period': 'year'})
        self.assertEqual(response.data['bonus']['count'], 5)

    def test_defective_total_amount(self):
        """defective.total_amount = 200"""
        self._auth_admin()
        response = self.client.get(self._url(), {'period': 'year'})
        self.assertAlmostEqual(float(response.data['defective']['total_amount']), 200.0, places=1)

    def test_expenses_total_amount(self):
        """expenses.total_amount = 600"""
        self._auth_admin()
        response = self.client.get(self._url(), {'period': 'year'})
        self.assertAlmostEqual(float(response.data['expenses']['total_amount']), 600.0, places=1)

    def test_grand_total(self):
        """grand_total = paid_debt(900) - expenses(600) = 300
        Бонусы НЕ вычитаются из grand_total.
        """
        self._auth_admin()
        response = self.client.get(self._url(), {'period': 'year'})
        self.assertAlmostEqual(float(response.data['grand_total']), 300.0, places=1)

    # --- Фильтры ---

    def test_specific_date_filter(self):
        self._auth_admin()
        today = timezone.localdate().isoformat()
        response = self.client.get(self._url(), {'date': today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_date_range_filter(self):
        self._auth_admin()
        today = timezone.localdate().isoformat()
        response = self.client.get(self._url(), {'date_from': today, 'date_to': today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_invalid_date_returns_400(self):
        self._auth_admin()
        response = self.client.get(self._url(), {'date': '13-01-2026'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_period_returns_400(self):
        self._auth_admin()
        response = self.client.get(self._url(), {'period': 'bad_value'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_future_range_returns_zeros(self):
        self._auth_admin()
        future = (timezone.localdate() + timedelta(days=30)).isoformat()
        response = self.client.get(self._url(), {'date_from': future, 'date_to': future})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertAlmostEqual(float(response.data['sold']['total_amount']), 0.0, places=1)

    def test_default_period_is_today(self):
        """Без параметров — статистика за сегодня (заказы есть)"""
        self._auth_admin()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Заказы created today → sold > 0
        self.assertAlmostEqual(float(response.data['sold']['total_amount']), 1800.0, places=1)


# =============================================================================
# 6. GET /api/reports/admin/partner-profile/
# =============================================================================

class AdminPartnerProfileViewTest(ReportsBaseTest):
    """Тесты GET /api/reports/admin/partner-profile/?partner_id={id}"""

    URL = '/api/reports/admin/partner-profile/'

    def _auth_admin(self):
        self.client.force_authenticate(user=self.admin)

    # --- Авторизация ---

    def test_requires_authentication(self):
        response = self.client.get(self.URL, {'partner_id': self.partner.id})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_partner_forbidden(self):
        self.client.force_authenticate(user=self.partner)
        response = self.client.get(self.URL, {'partner_id': self.partner.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_store_user_forbidden(self):
        self.client.force_authenticate(user=self.store_owner)
        response = self.client.get(self.URL, {'partner_id': self.partner.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_has_access(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- Валидация partner_id ---

    def test_missing_partner_id_returns_400(self):
        self._auth_admin()
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_partner_id_type_returns_400(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': 'abc'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nonexistent_partner_returns_404(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': 99999})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_partner_role_returns_404(self):
        """admin.id существует, но роль не partner → 404"""
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.admin.id})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Структура ответа (совпадает с /partners/profile/) ---

    def test_response_keys(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'period': 'year'})
        data = response.data
        for key in ['period', 'date_from', 'date_to', 'available_stores', 'filter', 'sales', 'totals']:
            self.assertIn(key, data, msg=f'Ключ {key!r} отсутствует')

    def test_sales_is_list(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'period': 'year'})
        self.assertIsInstance(response.data['sales'], list)

    def test_available_stores_is_list(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'period': 'year'})
        self.assertIsInstance(response.data['available_stores'], list)

    # --- Данные совпадают с /partners/profile/ ---

    def test_totals_piece_count(self):
        """totals.piece_count = 23 (как у партнёра)"""
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'period': 'year'})
        self.assertEqual(response.data['totals']['piece_count'], 23)

    def test_totals_total_amount(self):
        """totals.total_amount = 1800"""
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'period': 'year'})
        self.assertAlmostEqual(float(response.data['totals']['total_amount']), 1800.0, places=1)

    def test_totals_sales_count(self):
        """totals.sales_count = 3"""
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'period': 'year'})
        self.assertEqual(response.data['totals']['sales_count'], 3)

    def test_available_store_name(self):
        """available_stores содержит тестовый магазин"""
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'period': 'year'})
        names = [s['name'] for s in response.data['available_stores']]
        self.assertIn(self.store.name, names)

    # --- Фильтры ---

    def test_filter_by_store_id(self):
        self._auth_admin()
        response = self.client.get(self.URL, {
            'partner_id': self.partner.id,
            'period': 'year',
            'store_id': self.store.id,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for sale in response.data['sales']:
            self.assertEqual(sale['store_id'], self.store.id)

    def test_filter_by_wrong_store_id_returns_empty_sales(self):
        self._auth_admin()
        response = self.client.get(self.URL, {
            'partner_id': self.partner.id,
            'period': 'year',
            'store_id': 99999,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['sales']), 0)

    def test_specific_date_filter(self):
        self._auth_admin()
        today = timezone.localdate().isoformat()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'date': today})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_future_date_returns_empty_sales(self):
        self._auth_admin()
        future = (timezone.localdate() + timedelta(days=30)).isoformat()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'date': future})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['sales']), 0)

    def test_invalid_date_format_returns_400(self):
        self._auth_admin()
        response = self.client.get(self.URL, {'partner_id': self.partner.id, 'date': '13-01-2026'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_date_range_filter(self):
        self._auth_admin()
        today = timezone.localdate().isoformat()
        response = self.client.get(self.URL, {
            'partner_id': self.partner.id,
            'date_from': today,
            'date_to': today,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
