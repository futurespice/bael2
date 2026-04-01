from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from orders.models import StoreOrder, StoreOrderItem, StoreOrderStatus
from products.models import Product
from stores.models import City, PartnerInventory, Region, Store
from users.models import User


class ConfirmBasketInsufficientReservationTest(TestCase):
    """
    confirm_basket должен вернуть HTTP 400 (не 500), если
    complete_reservation бросает ValidationError (reserved_quantity < item.quantity).
    Транзакция должна откатиться: заказ остаётся IN_TRANSIT.
    """

    def setUp(self):
        self.partner = User.objects.create_user(
            phone='+996700100001',
            email='partner@edge.test',
            name='Partner',
            second_name='Edge',
            password='pass',
            role='partner',
        )
        store_user = User.objects.create_user(
            phone='+996700100002',
            email='store@edge.test',
            name='Store',
            second_name='Edge',
            password='pass',
            role='store',
        )
        region = Region.objects.create(name='Edge Region')
        city = City.objects.create(name='Edge City', region=region)
        self.store = Store.objects.create(
            name='Edge Store',
            owner=store_user,
            address='Edge St 1',
            region=region,
            city=city,
            inn='000000000001',
            phone='+996555000001',
            owner_name='Edge Owner',
            is_active=True,
            approval_status='approved',
        )
        self.product = Product.objects.create(
            name='Edge Product',
            manual_price=Decimal('100.00'),
            stock_quantity=Decimal('100'),
            is_available=True,
        )

        # Заказ уже в статусе IN_TRANSIT (минуем approve)
        self.order = StoreOrder.objects.create(
            order_type='preorder',
            store=self.store,
            partner=self.partner,
            created_by=store_user,
            status=StoreOrderStatus.IN_TRANSIT,
            total_amount=Decimal('500.00'),
        )
        StoreOrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=Decimal('5'),
            price=Decimal('100.00'),
            total=Decimal('500.00'),
        )

        # PartnerInventory: товар есть, но резерв = 0 (не резервировался)
        PartnerInventory.objects.create(
            partner=self.partner,
            product=self.product,
            quantity=Decimal('10'),
            reserved_quantity=Decimal('0'),  # вызовет ValidationError в complete_reservation
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.partner)
        self.url = f'/api/stores/stores/{self.store.id}/basket/confirm/'

    def test_returns_400_not_500(self):
        response = self.client.post(self.url, {'prepayment_amount': '0'}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.data)

    def test_transaction_rolled_back(self):
        """Заказ должен остаться IN_TRANSIT, инвентарь — без изменений."""
        self.client.post(self.url, {'prepayment_amount': '0'}, format='json')

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, StoreOrderStatus.IN_TRANSIT)

        inv = PartnerInventory.objects.get(partner=self.partner, product=self.product)
        self.assertEqual(inv.quantity, Decimal('10'))
        self.assertEqual(inv.reserved_quantity, Decimal('0'))

        # Долг магазина не изменился
        self.store.refresh_from_db()
        self.assertEqual(self.store.debt, Decimal('0'))
