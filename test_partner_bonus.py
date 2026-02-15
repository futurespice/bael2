
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from stores.models import Store, PartnerInventory, Region, City
from products.models import Product, ProductUnit
from orders.services import PartnerRequestService, OrderWorkflowService, BasketService, ManualOrderService, OrderItemData
from orders.models import PartnerRequestType, StoreOrderStatus
from stores.services import PartnerInventoryService

User = get_user_model()

class PartnerBonusTest(TestCase):
    def setUp(self):
        self.partner_user = User.objects.create_user(
            phone='+996555123456',
            email='partner@test.com',
            name='Partner',
            second_name='Test',
            password='password',
            role='partner'
        )
        self.admin_user = User.objects.create_superuser(
            phone='+996555000000',
            email='admin@test.com',
            name='Admin',
            second_name='User',
            password='password',
            role='admin'
        )
        
        self.store_user = User.objects.create_user(
            phone='+996555111222',
            email='store_owner@test.com',
            name='Store',
            second_name='Owner',
            password='password',
            role='store'
        )
        
        self.product_bonus = Product.objects.create(
            name='Bonus Product',
            unit=ProductUnit.PIECE,
            manual_price=Decimal('100.00'),
            stock_quantity=Decimal('1000'),
            is_bonus=True
        )
        
        self.region = Region.objects.create(name='Test Region')
        self.city = City.objects.create(name='Test City', region=self.region)
        
        self.store = Store.objects.create(
            name='Test Store',
            owner=self.store_user,
            address='Test Address',
            region=self.region,
            city=self.city,
            inn='12345678901234',
            phone='+996555987654',
            owner_name='Test Owner',
            is_active=True,
            approval_status='approved'
        )

    def test_partner_bonus_workflow(self):
        """
        Test full workflow for bonus items:
        1. Partner requests bonus items.
        2. Admin approves -> items go to PartnerInventory(is_bonus=True).
        3. Partner makes Manual Order using bonus items.
        4. Verify inventory deduction.
        """
        
        # 1. Create Request for Bonus Items (and regular)
        items = [
            {'product': self.product_bonus.id, 'quantity': 10, 'is_bonus': False},
            {'product': self.product_bonus.id, 'quantity': 5, 'is_bonus': True},
        ]
        
        request = PartnerRequestService.create_request(
            partner=self.partner_user,
            request_type=PartnerRequestType.REQUEST,
            items=items,
            notes="Bonus test request"
        )
        
        self.assertEqual(request.items.count(), 2)
        item_regular = request.items.get(is_bonus=False)
        item_bonus = request.items.get(is_bonus=True)
        
        self.assertEqual(item_regular.quantity, Decimal('10'))
        self.assertEqual(item_bonus.quantity, Decimal('5'))
        
        # 2. Admin Approves
        PartnerRequestService.approve_request(request=request, approved_by=self.admin_user)
        
        # Verify PartnerInventory
        inv_regular = PartnerInventory.objects.get(
            partner=self.partner_user, 
            product=self.product_bonus, 
            is_bonus=False
        )
        inv_bonus = PartnerInventory.objects.get(
            partner=self.partner_user, 
            product=self.product_bonus, 
            is_bonus=True
        )
        
        self.assertEqual(inv_regular.quantity, Decimal('10'))
        self.assertEqual(inv_bonus.quantity, Decimal('5'))
        
        # 3. Create Manual Order using Bonus Items
        # Scenario: Partner gives 2 bonus items to store
        
        order_items_data = [
            OrderItemData(
                product_id=self.product_bonus.id,
                quantity=Decimal('2'),
                is_bonus=True
            )
        ]
        
        order = ManualOrderService.create_manual_order(
            partner=self.partner_user,
            store=self.store,
            items=order_items_data
        )
        
        # Verify Order Items
        self.assertEqual(order.items.count(), 1)
        order_item = order.items.first()
        self.assertTrue(order_item.is_bonus)
        self.assertEqual(order_item.quantity, Decimal('2'))
        self.assertEqual(order_item.total, Decimal('0'))
        
        # Verify Inventory Deduction
        inv_bonus.refresh_from_db()
        self.assertEqual(inv_bonus.quantity, Decimal('3'))  # 5 - 2 = 3
        
        inv_regular.refresh_from_db()
        self.assertEqual(inv_regular.quantity, Decimal('10')) # Unchanged

    def test_manual_order_auto_bonus(self):
        """
        Test manual order with auto-calculated bonus.
        1. Partner has sufficient Paid stock AND Bonus stock.
        2. Partner creates Manual Order for substantial quantity.
        3. Service auto-calculates bonus.
        4. Service deducts from Paid and Bonus inventory.
        """
        
        # Setup inventory
        PartnerInventoryService.add_to_inventory(
            partner=self.partner_user,
            product=self.product_bonus,
            quantity=Decimal('100'),
            is_bonus=False
        )
        PartnerInventoryService.add_to_inventory(
            partner=self.partner_user,
            product=self.product_bonus,
            quantity=Decimal('10'), # Enough for auto bonus
            is_bonus=True
        )
        
        order_items_data = [
            OrderItemData(
                product_id=self.product_bonus.id,
                quantity=Decimal('25'),
                is_bonus=False
            )
        ]
        
        order = ManualOrderService.create_manual_order(
            partner=self.partner_user,
            store=self.store,
            items=order_items_data
        )
        
        # Verify Order Items
        # Should have 1 Paid item (25 qty) and 1 Bonus item (2 qty)
        self.assertEqual(order.items.count(), 2)
        item_paid = order.items.get(is_bonus=False)
        item_bonus = order.items.get(is_bonus=True)
        
        self.assertEqual(item_paid.quantity, Decimal('25'))
        self.assertEqual(item_bonus.quantity, Decimal('2'))
        
        # Verify Inventory Deduction
        inv_paid = PartnerInventory.objects.get(partner=self.partner_user, product=self.product_bonus, is_bonus=False)
        inv_bonus = PartnerInventory.objects.get(partner=self.partner_user, product=self.product_bonus, is_bonus=True)
        
        self.assertEqual(inv_paid.quantity, Decimal('75'))  # 100 - 25
        self.assertEqual(inv_bonus.quantity, Decimal('8'))  # 10 - 2

    def test_manual_order_auto_bonus_insufficient(self):
        """
        Test manual order auto-bonus when Partner has NO bonus stock.
        Bonus should NOT be granted.
        """
        
        # Setup inventory (Paid only)
        PartnerInventoryService.add_to_inventory(
            partner=self.partner_user,
            product=self.product_bonus,
            quantity=Decimal('100'),
            is_bonus=False
        )
        # No bonus inventory
        
        order_items_data = [
            OrderItemData(
                product_id=self.product_bonus.id,
                quantity=Decimal('25'),
                is_bonus=False
            )
        ]
        
        order = ManualOrderService.create_manual_order(
            partner=self.partner_user,
            store=self.store,
            items=order_items_data
        )
        
        # Verify Order Items
        # Should have 1 Paid item (25 qty) and NO Bonus item (because partner has no bonus stock)
        self.assertEqual(order.items.count(), 1)
        item_paid = order.items.get(is_bonus=False)
        self.assertEqual(item_paid.quantity, Decimal('25'))
        
        # Verify Inventory Deduction
        inv_paid = PartnerInventory.objects.get(partner=self.partner_user, product=self.product_bonus, is_bonus=False)
        self.assertEqual(inv_paid.quantity, Decimal('75'))
