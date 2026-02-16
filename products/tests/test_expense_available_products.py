"""Tests for products-without and add-products endpoints on ExpenseViewSet."""

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


class BaseExpenseProductsTest(TestCase):
    """Shared setUp for both endpoint test classes."""

    def setUp(self):
        self.client = APIClient()

        self.admin = User.objects.create(
            phone='+996700000001',
            email='admin@test.com',
            name='Test',
            second_name='Admin',
            role='admin',
            is_active=True,
        )
        self.client.force_authenticate(user=self.admin)

        self.regular_overhead = Expense.objects.create(
            name='Test Logistics',
            expense_type=ExpenseType.OVERHEAD,
            apply_type=ApplyType.REGULAR,
            monthly_amount=Decimal('10000.00'),
            is_active=True,
        )

        self.universal_overhead = Expense.objects.create(
            name='Test Rent',
            expense_type=ExpenseType.OVERHEAD,
            apply_type=ApplyType.UNIVERSAL,
            monthly_amount=Decimal('50000.00'),
            is_active=True,
        )

        self.physical_expense = Expense.objects.create(
            name='Test Flour',
            expense_type=ExpenseType.PHYSICAL,
            unit_type='per_weight',
            price_per_unit=Decimal('50.00'),
            is_active=True,
        )

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


# =============================================================================
# GET /api/products/expenses/{id}/products-without/
# =============================================================================

class ProductsWithoutTest(BaseExpenseProductsTest):
    """Tests for GET /api/products/expenses/{id}/products-without/."""

    def _url(self, expense_id):
        return f'/api/products/expenses/{expense_id}/products-without/'

    # --- Happy path ---

    def test_get_products_without_expense(self):
        """Products with expense are excluded, rest are returned."""
        for product in self.products[:2]:
            ProductRecipe.objects.create(
                product=product, expense=self.regular_overhead,
            )

        response = self.client.get(self._url(self.regular_overhead.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        returned_names = [p['name'] for p in response.data['results']]
        self.assertIn('Product 3', returned_names)
        self.assertNotIn('Product 1', returned_names)

    def test_returns_all_when_none_linked(self):
        response = self.client.get(self._url(self.regular_overhead.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 5)

    def test_returns_empty_when_all_linked(self):
        for product in self.products:
            ProductRecipe.objects.create(
                product=product, expense=self.regular_overhead,
            )
        response = self.client.get(self._url(self.regular_overhead.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_results_sorted_by_name(self):
        response = self.client.get(self._url(self.regular_overhead.id))
        names = [p['name'] for p in response.data['results']]
        self.assertEqual(names, sorted(names))

    # --- Filters ---

    def test_search_filter(self):
        response = self.client.get(
            self._url(self.regular_overhead.id), {'search': 'Product 3'},
        )
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['name'], 'Product 3')

    def test_search_case_insensitive(self):
        response = self.client.get(
            self._url(self.regular_overhead.id), {'search': 'product 3'},
        )
        self.assertEqual(response.data['count'], 1)

    def test_is_active_false(self):
        self.products[0].is_active = False
        self.products[0].save()
        response = self.client.get(
            self._url(self.regular_overhead.id), {'is_active': 'false'},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['name'], 'Product 1')

    def test_inactive_excluded_by_default(self):
        self.products[0].is_active = False
        self.products[0].save()
        response = self.client.get(self._url(self.regular_overhead.id))
        self.assertEqual(response.data['count'], 4)
        returned_ids = [p['id'] for p in response.data['results']]
        self.assertNotIn(self.products[0].id, returned_ids)

    def test_unavailable_excluded(self):
        self.products[0].is_available = False
        self.products[0].save()
        response = self.client.get(self._url(self.regular_overhead.id))
        self.assertEqual(response.data['count'], 4)

    # --- Pagination ---

    def test_pagination(self):
        response = self.client.get(
            self._url(self.regular_overhead.id), {'page_size': 2},
        )
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNotNone(response.data['next'])
        self.assertEqual(response.data['count'], 5)

    def test_pagination_second_page(self):
        response = self.client.get(
            self._url(self.regular_overhead.id), {'page_size': 3, 'page': 2},
        )
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNone(response.data['next'])

    # --- Validation ---

    def test_400_for_physical(self):
        response = self.client.get(self._url(self.physical_expense.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_for_universal(self):
        response = self.client.get(self._url(self.universal_overhead.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_404_for_nonexistent(self):
        response = self.client.get(self._url(99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Auth ---

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self._url(self.regular_overhead.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_forbidden(self):
        partner = User.objects.create(
            phone='+996700000002', email='p@test.com',
            name='P', second_name='P', role='partner', is_active=True,
        )
        self.client.force_authenticate(user=partner)
        response = self.client.get(self._url(self.regular_overhead.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# =============================================================================
# POST /api/products/expenses/{id}/add-products/
# =============================================================================

class AddProductsTest(BaseExpenseProductsTest):
    """Tests for POST /api/products/expenses/{id}/add-products/."""

    def _url(self, expense_id):
        return f'/api/products/expenses/{expense_id}/add-products/'

    # --- Happy path ---

    def test_add_products_success(self):
        """Creates ProductRecipe records for given product IDs."""
        ids = [self.products[0].id, self.products[1].id, self.products[2].id]
        response = self.client.post(
            self._url(self.regular_overhead.id),
            {'product_ids': ids},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['created'], 3)
        self.assertEqual(response.data['skipped'], 0)
        self.assertEqual(
            ProductRecipe.objects.filter(expense=self.regular_overhead).count(),
            3,
        )

    def test_skips_duplicates(self):
        """Already linked products are skipped (get_or_create)."""
        ProductRecipe.objects.create(
            product=self.products[0], expense=self.regular_overhead,
        )

        ids = [self.products[0].id, self.products[1].id]
        response = self.client.post(
            self._url(self.regular_overhead.id),
            {'product_ids': ids},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['created'], 1)
        self.assertEqual(response.data['skipped'], 1)
        self.assertEqual(
            ProductRecipe.objects.filter(expense=self.regular_overhead).count(),
            2,
        )

    def test_all_duplicates(self):
        """All products already linked — created=0."""
        for p in self.products[:2]:
            ProductRecipe.objects.create(product=p, expense=self.regular_overhead)

        ids = [self.products[0].id, self.products[1].id]
        response = self.client.post(
            self._url(self.regular_overhead.id),
            {'product_ids': ids},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['created'], 0)
        self.assertEqual(response.data['skipped'], 2)

    def test_products_without_reflects_add(self):
        """After adding products, products-without no longer lists them."""
        ids = [self.products[0].id, self.products[1].id]
        self.client.post(
            self._url(self.regular_overhead.id),
            {'product_ids': ids},
            format='json',
        )

        without_url = f'/api/products/expenses/{self.regular_overhead.id}/products-without/'
        response = self.client.get(without_url)
        self.assertEqual(response.data['count'], 3)
        returned_ids = [p['id'] for p in response.data['results']]
        self.assertNotIn(self.products[0].id, returned_ids)
        self.assertNotIn(self.products[1].id, returned_ids)

    # --- Validation ---

    def test_400_for_physical(self):
        response = self.client.post(
            self._url(self.physical_expense.id),
            {'product_ids': [self.products[0].id]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_for_universal(self):
        response = self.client.post(
            self._url(self.universal_overhead.id),
            {'product_ids': [self.products[0].id]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_for_empty_list(self):
        response = self.client.post(
            self._url(self.regular_overhead.id),
            {'product_ids': []},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_for_missing_field(self):
        response = self.client.post(
            self._url(self.regular_overhead.id),
            {},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_for_invalid_product_ids(self):
        response = self.client.post(
            self._url(self.regular_overhead.id),
            {'product_ids': [99999]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('99999', response.data['error'])

    def test_404_for_nonexistent_expense(self):
        response = self.client.post(
            self._url(99999),
            {'product_ids': [self.products[0].id]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Auth ---

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            self._url(self.regular_overhead.id),
            {'product_ids': [self.products[0].id]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_forbidden(self):
        partner = User.objects.create(
            phone='+996700000003', email='p2@test.com',
            name='P', second_name='P', role='partner', is_active=True,
        )
        self.client.force_authenticate(user=partner)
        response = self.client.post(
            self._url(self.regular_overhead.id),
            {'product_ids': [self.products[0].id]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
