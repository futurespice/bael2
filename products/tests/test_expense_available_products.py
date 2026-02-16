"""Tests for the available-products endpoint on ExpenseViewSet."""

from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from products.models import (
    Expense,
    ExpenseType,
    ApplyType,
    Product,
    ProductRecipe,
)
from users.models import User


class ExpenseAvailableProductsTest(TestCase):
    """Tests for GET /api/products/expenses/{id}/available-products/."""

    def setUp(self):
        self.client = APIClient()

        # Admin user
        self.admin = User.objects.create(
            phone='+996700000001',
            email='admin@test.com',
            name='Test',
            second_name='Admin',
            role='admin',
            is_active=True,
        )
        self.client.force_authenticate(user=self.admin)

        # Regular overhead expense
        self.regular_overhead = Expense.objects.create(
            name='Test Logistics',
            expense_type=ExpenseType.OVERHEAD,
            apply_type=ApplyType.REGULAR,
            monthly_amount=Decimal('10000.00'),
            is_active=True,
        )

        # Universal overhead expense
        self.universal_overhead = Expense.objects.create(
            name='Test Rent',
            expense_type=ExpenseType.OVERHEAD,
            apply_type=ApplyType.UNIVERSAL,
            monthly_amount=Decimal('50000.00'),
            is_active=True,
        )

        # Physical expense
        self.physical_expense = Expense.objects.create(
            name='Test Flour',
            expense_type=ExpenseType.PHYSICAL,
            unit_type='per_weight',
            price_per_unit=Decimal('50.00'),
            is_active=True,
        )

        # Products
        self.products = []
        for i in range(1, 6):
            product = Product.objects.create(
                name=f'Product {i}',
                manual_price=Decimal('100.00'),
                stock_quantity=Decimal('100'),
                is_active=True,
                is_available=True,
                unit='kg',
            )
            self.products.append(product)

    def _url(self, expense_id):
        return f'/api/products/expenses/{expense_id}/available-products/'

    # =========================================================================
    # Happy path
    # =========================================================================

    def test_get_available_products_success(self):
        """Products with expense are excluded, rest are returned."""
        # Link expense to first 2 products
        for product in self.products[:2]:
            ProductRecipe.objects.create(
                product=product,
                expense=self.regular_overhead,
            )

        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        returned_names = [p['name'] for p in response.data['results']]
        self.assertIn('Product 3', returned_names)
        self.assertIn('Product 4', returned_names)
        self.assertIn('Product 5', returned_names)
        self.assertNotIn('Product 1', returned_names)
        self.assertNotIn('Product 2', returned_names)

    def test_returns_all_when_no_products_have_expense(self):
        """All active/available products returned when none have the expense."""
        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 5)

    def test_returns_empty_when_all_products_have_expense(self):
        """Empty list when all products already have the expense."""
        for product in self.products:
            ProductRecipe.objects.create(
                product=product,
                expense=self.regular_overhead,
            )

        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(len(response.data['results']), 0)

    def test_results_sorted_by_name(self):
        """Results are ordered alphabetically by name."""
        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [p['name'] for p in response.data['results']]
        self.assertEqual(names, sorted(names))

    # =========================================================================
    # Filters
    # =========================================================================

    def test_search_filter(self):
        """Search by product name works."""
        response = self.client.get(
            self._url(self.regular_overhead.id),
            {'search': 'Product 3'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['name'], 'Product 3')

    def test_search_filter_case_insensitive(self):
        """Search is case-insensitive."""
        response = self.client.get(
            self._url(self.regular_overhead.id),
            {'search': 'product 3'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_is_active_filter_false(self):
        """is_active=false returns only inactive products."""
        self.products[0].is_active = False
        self.products[0].save()

        response = self.client.get(
            self._url(self.regular_overhead.id),
            {'is_active': 'false'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['name'], 'Product 1')

    def test_inactive_products_excluded_by_default(self):
        """Inactive products are excluded when is_active is not specified."""
        self.products[0].is_active = False
        self.products[0].save()

        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 4)
        returned_ids = [p['id'] for p in response.data['results']]
        self.assertNotIn(self.products[0].id, returned_ids)

    def test_unavailable_products_excluded(self):
        """Products with is_available=False are excluded."""
        self.products[0].is_available = False
        self.products[0].save()

        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 4)
        returned_ids = [p['id'] for p in response.data['results']]
        self.assertNotIn(self.products[0].id, returned_ids)

    # =========================================================================
    # Pagination
    # =========================================================================

    def test_pagination(self):
        """Pagination works with page_size parameter."""
        response = self.client.get(
            self._url(self.regular_overhead.id),
            {'page_size': 2},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNotNone(response.data['next'])
        self.assertEqual(response.data['count'], 5)

    def test_pagination_second_page(self):
        """Second page returns remaining items."""
        response = self.client.get(
            self._url(self.regular_overhead.id),
            {'page_size': 3, 'page': 2},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNone(response.data['next'])

    # =========================================================================
    # Validation
    # =========================================================================

    def test_returns_400_for_physical_expense(self):
        """Physical expenses return 400."""
        response = self.client.get(self._url(self.physical_expense.id))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('overhead expenses', response.data['error'].lower())

    def test_returns_400_for_universal_expense(self):
        """Universal overhead expenses return 400."""
        response = self.client.get(self._url(self.universal_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('regular expenses', response.data['error'].lower())

    def test_returns_404_for_nonexistent_expense(self):
        """Non-existent expense ID returns 404."""
        response = self.client.get(self._url(99999))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # Authentication / Permissions
    # =========================================================================

    def test_requires_authentication(self):
        """Unauthenticated requests return 401."""
        self.client.force_authenticate(user=None)
        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_forbidden(self):
        """Non-admin users return 403."""
        partner = User.objects.create(
            phone='+996700000002',
            email='partner@test.com',
            name='Test',
            second_name='Partner',
            role='partner',
            is_active=True,
        )
        self.client.force_authenticate(user=partner)

        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
