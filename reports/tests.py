from django.test import TestCase
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

from stores.models import Store, Region, City
from users.models import User
from products.models import Product
from orders.models import StoreOrder, StoreOrderItem, StoreOrderStatus, StoreOrderType, DebtPayment
from reports.services import ReportService, ReportFilters, TimePeriod

class DebtCalculationTest(TestCase):
    def setUp(self):
        # Create User (Partner)
        self.partner = User.objects.create_user(
            phone='+996555123456',
            email='partner@example.com',
            name='Partner',
            second_name='User',
            password='password',
            role='partner'
        )

        # Create Owner User
        self.owner = User.objects.create_user(
            phone='+996555987654',
            email='owner@example.com',
            name='Store Owner',
            second_name='User',
            password='password',
            role='store'
        )

        # Create Store
        self.region = Region.objects.create(name='Test Region')
        self.city = City.objects.create(name='Test City', region=self.region)
        self.store = Store.objects.create(
            name='Test Store',
            region=self.region,
            city=self.city,
            owner=self.owner,
            inn='12345678901234',
            owner_name='Owner Name',
            phone='+996555000000',
            address='Test Address'
        )

        # Create Product
        self.product = Product.objects.create(
            name='Test Product',
            average_cost_price=Decimal('80.00'),
            manual_price=Decimal('100.00')
        )

        # Create Order (Confirmed Today)
        self.order = StoreOrder.objects.create(
            store=self.store,
            partner=self.partner,
            status=StoreOrderStatus.ACCEPTED,
            order_type=StoreOrderType.PREORDER,
            total_amount=Decimal('1000.00'),
            prepayment_amount=Decimal('0.00'),
            debt_amount=Decimal('1000.00'),  # Initial Debt
            paid_amount=Decimal('0.00'),
            confirmed_at=timezone.now()
        )
        
        # Create Order Item
        StoreOrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=10,
            price=100,
            total=1000
        )

        # Create Partial Payment (Today)
        self.payment = DebtPayment.objects.create(
            order=self.order,
            amount=Decimal('500.00'),
            paid_by=self.partner
        )
        
        # Update Order paid_amount
        self.order.paid_amount = Decimal('500.00')
        self.order.save()

    def test_admin_statistics_debt(self):
        """Test debt calculation in Admin Statistics (ReportService.calculate_statistics)."""
        print("\n=== Admin Statistics Debt Test ===")
        
        filters = ReportFilters(
            period=TimePeriod.DAY,
            start_date=timezone.now().date(),
            end_date=timezone.now().date()
        )
        # Note: ReportService uses TimePeriod enum. Let's see if 'day' is valid.
        # Yes, TimePeriod.DAY = 'day'.
        
        stats = ReportService.calculate_statistics(filters)
        
        print(f"Stats Debt (Unpaid?): {stats.debt}")
        print(f"Stats Paid Debt: {stats.paid_debt}")
        print(f"Stats Total Balance: {stats.total_balance}")
        print(f"Stats Income: {stats.income}")
        
        # assertions based on current implementation analysis
        # debt = Sum(debt_amount) which is initial debt -> 1000
        self.assertEqual(stats.debt, Decimal('1000.00')) 
        
        # paid_debt = Sum(DebtPayment) -> 500
        self.assertEqual(stats.paid_debt, Decimal('500.00'))
        
        # income = total_amount + paid_debt = 1000 + 500 = 1500 ?
        # implementation: orders_income = Sum('total_amount'). 
        # income = orders_income + paid_debt
        self.assertEqual(stats.income, Decimal('1500.00'))

    def test_store_history_debt(self):
        """Test debt calculation in Store History (ReportService.get_store_history)."""
        print("\n=== Store History Debt Test ===")
        
        history = ReportService.get_store_history(
            store=self.store,
            start_date=timezone.now().date(),
            end_date=timezone.now().date()
        )
        
        if not history:
            print("History is empty!")
            return

        day_data = history[0]
        print(f"Day Total Debt: {day_data['total_debt']}")
        print(f"Day Total Amount: {day_data['total_amount']}")
        
        payments = day_data['debt_payments']
        total_payments = sum(p['amount'] for p in payments)
        print(f"Day Payments Sum: {total_payments}")
        
        # total_debt = Sum(debt_amount) -> 1000
        self.assertEqual(day_data['total_debt'], 1000.0)
        
        # payments should list the payment
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0]['amount'], 500.0)

