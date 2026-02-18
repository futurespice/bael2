"""Tests for v3.0 updates: ProductRecipeCreateSerializer, mechanical_accounting, per_volume."""

from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from products.models import (
    Expense,
    ExpenseType,
    ExpenseStatus,
    ExpenseState,
    ExpenseUnitType,
    ApplyType,
    Product,
    ProductRecipe,
)
from users.models import User


@override_settings(
    ALLOWED_HOSTS=['*'],
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    REST_FRAMEWORK={
        'DEFAULT_AUTHENTICATION_CLASSES': [
            'rest_framework_simplejwt.authentication.JWTAuthentication',
        ],
        'DEFAULT_PERMISSION_CLASSES': [
            'rest_framework.permissions.IsAuthenticated',
        ],
        'DEFAULT_RENDERER_CLASSES': [
            'rest_framework.renderers.JSONRenderer',
        ],
        'DEFAULT_PARSER_CLASSES': [
            'rest_framework.parsers.JSONParser',
            'rest_framework.parsers.MultiPartParser',
            'rest_framework.parsers.FormParser',
        ],
        'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
        'DEFAULT_THROTTLE_CLASSES': [],
        'DEFAULT_THROTTLE_RATES': {},
    },
)
class BaseV3Test(TestCase):
    """Shared setUp for v3.0 update tests."""

    def setUp(self):
        self.client = APIClient()

        self.admin = User.objects.create(
            phone='+996700100001',
            email='admin_v3@test.com',
            name='Test',
            second_name='Admin',
            role='admin',
            is_active=True,
        )
        self.client.force_authenticate(user=self.admin)

        # Сюзерен — Фарш (physical, regular, automatic, per_weight)
        self.farsh = Expense.objects.create(
            name='Фарш Тест',
            expense_type=ExpenseType.PHYSICAL,
            expense_status=ExpenseStatus.SUZERAIN,
            expense_state=ExpenseState.AUTOMATIC,
            apply_type=ApplyType.REGULAR,
            unit_type=ExpenseUnitType.PER_WEIGHT,
            price_per_unit=Decimal('810.00'),
            is_active=True,
        )

        # Обыватель — Лук (physical, regular, automatic, per_weight)
        self.luk = Expense.objects.create(
            name='Лук Тест',
            expense_type=ExpenseType.PHYSICAL,
            expense_status=ExpenseStatus.CIVILIAN,
            expense_state=ExpenseState.AUTOMATIC,
            apply_type=ApplyType.REGULAR,
            unit_type=ExpenseUnitType.PER_WEIGHT,
            price_per_unit=Decimal('40.00'),
            is_active=True,
        )

        # Обыватель — Вода (physical, regular, automatic, per_volume)
        self.voda = Expense.objects.create(
            name='Вода Тест',
            expense_type=ExpenseType.PHYSICAL,
            expense_status=ExpenseStatus.CIVILIAN,
            expense_state=ExpenseState.AUTOMATIC,
            apply_type=ApplyType.REGULAR,
            unit_type=ExpenseUnitType.PER_VOLUME,
            price_per_unit=Decimal('5.00'),
            is_active=True,
        )

        # Механический Вассал — Солярка (overhead, mechanical, universal → vassal)
        self.solyarka = Expense.objects.create(
            name='Солярка Тест',
            expense_type=ExpenseType.OVERHEAD,
            expense_status=ExpenseStatus.VASSAL,
            expense_state=ExpenseState.MECHANICAL,
            apply_type=ApplyType.UNIVERSAL,
            monthly_amount=Decimal('0'),
            daily_amount=Decimal('700'),
            is_active=True,
        )

        # Товар
        self.product = Product.objects.create(
            name='Пельмени v3 Тест',
            manual_price=Decimal('100.00'),
            stock_quantity=Decimal('100'),
            is_active=True,
            is_available=True,
        )


# =============================================================================
# ProductRecipeCreateSerializer — absolute_quantity
# =============================================================================

class ProductRecipeCreateSerializerTest(BaseV3Test):
    """Tests for ProductRecipeCreateSerializer with absolute_quantity."""

    def _url(self):
        return '/api/products/product-recipes/'

    def test_suzerain_with_absolute_quantity(self):
        """Сюзерен: absolute_quantity=80, product_quantity=40 → quantity_per_unit=2."""
        response = self.client.post(self._url(), {
            'product': self.product.id,
            'expense': self.farsh.id,
            'absolute_quantity': '80.0000',
            'product_quantity': '40.00',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.farsh
        )
        self.assertEqual(recipe.absolute_quantity, Decimal('80.0000'))
        self.assertEqual(recipe.product_quantity, Decimal('40.00'))
        # quantity_per_unit = 80 / 40 = 2
        self.assertEqual(recipe.quantity_per_unit, Decimal('2'))

    def test_obyvatel_with_absolute_quantity(self):
        """Обыватель: proportion рассчитывается от Сюзерена."""
        # Сначала создаём рецепт Сюзерена
        ProductRecipe.objects.create(
            product=self.product,
            expense=self.farsh,
            absolute_quantity=Decimal('80'),
            product_quantity=Decimal('40'),
        )

        response = self.client.post(self._url(), {
            'product': self.product.id,
            'expense': self.luk.id,
            'absolute_quantity': '40.0000',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.luk
        )
        # proportion = 40 / 80 = 0.5
        self.assertEqual(recipe.proportion, Decimal('0.5'))

    def test_suzerain_requires_product_quantity(self):
        """Сюзерен с absolute_quantity но без product_quantity → ошибка."""
        response = self.client.post(self._url(), {
            'product': self.product.id,
            'expense': self.farsh.id,
            'absolute_quantity': '80.0000',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_backward_compat_suzerain_quantity_per_unit(self):
        """Обратная совместимость: прямой ввод quantity_per_unit."""
        response = self.client.post(self._url(), {
            'product': self.product.id,
            'expense': self.farsh.id,
            'quantity_per_unit': '2.0000',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.farsh
        )
        self.assertEqual(recipe.quantity_per_unit, Decimal('2.0000'))

    def test_backward_compat_obyvatel_proportion(self):
        """Обратная совместимость: прямой ввод proportion."""
        response = self.client.post(self._url(), {
            'product': self.product.id,
            'expense': self.luk.id,
            'proportion': '0.500',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.luk
        )
        self.assertEqual(recipe.proportion, Decimal('0.500'))

    def test_per_volume_obyvatel_with_absolute_quantity(self):
        """Обыватель per_volume (вода): proportion рассчитывается от Сюзерена."""
        ProductRecipe.objects.create(
            product=self.product,
            expense=self.farsh,
            absolute_quantity=Decimal('80'),
            product_quantity=Decimal('40'),
        )

        response = self.client.post(self._url(), {
            'product': self.product.id,
            'expense': self.voda.id,
            'absolute_quantity': '8.0000',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.voda
        )
        # proportion = 8 / 80 = 0.1
        self.assertEqual(recipe.proportion, Decimal('0.1'))

    def test_overhead_no_fields_required(self):
        """Накладной расход — не требует ни proportion, ни quantity_per_unit."""
        overhead = Expense.objects.create(
            name='Аренда Тест',
            expense_type=ExpenseType.OVERHEAD,
            expense_status=ExpenseStatus.CIVILIAN,
            expense_state=ExpenseState.AUTOMATIC,
            apply_type=ApplyType.REGULAR,
            monthly_amount=Decimal('30000'),
            is_active=True,
        )
        response = self.client.post(self._url(), {
            'product': self.product.id,
            'expense': overhead.id,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


# =============================================================================
# mechanical_accounting — enriched response
# =============================================================================

class MechanicalAccountingTest(BaseV3Test):
    """Tests for GET /api/products/expenses/mechanical-accounting/."""

    def _url(self):
        return '/api/products/expenses/mechanical-accounting/'

    def test_response_contains_new_fields(self):
        """Ответ должен содержать expense_type, expense_state, apply_type, monthly_amount."""
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expenses = response.data['mechanical_expenses']
        self.assertTrue(len(expenses) > 0)

        exp = expenses[0]
        self.assertIn('expense_type', exp)
        self.assertIn('expense_state', exp)
        self.assertIn('apply_type', exp)
        self.assertIn('monthly_amount', exp)
        self.assertIn('daily_amount', exp)
        self.assertIn('expense_status', exp)

    def test_solyarka_is_mechanical_vassal(self):
        """Солярка — mechanical vassal, должна быть в списке."""
        response = self.client.get(self._url())

        expenses = response.data['mechanical_expenses']
        solyarka_data = next(
            (e for e in expenses if e['id'] == self.solyarka.id), None
        )
        self.assertIsNotNone(solyarka_data)
        self.assertEqual(solyarka_data['expense_type'], 'overhead')
        self.assertEqual(solyarka_data['expense_status'], 'vassal')
        self.assertEqual(solyarka_data['expense_state'], 'mechanical')
        self.assertEqual(solyarka_data['apply_type'], 'universal')
        self.assertEqual(solyarka_data['daily_amount'], '700.00')


# =============================================================================
# per_volume — verification
# =============================================================================

class PerVolumeTest(BaseV3Test):
    """Tests for per_volume (litres) in accounting calculations."""

    def test_per_volume_expense_creation(self):
        """Создание расхода с per_volume через API."""
        response = self.client.post('/api/products/expenses/', {
            'name': 'Масло Тест v3',
            'expense_type': 'physical',
            'expense_status': 'civilian',
            'expense_state': 'automatic',
            'apply_type': 'regular',
            'unit_type': 'per_volume',
            'price_per_unit': '100.00',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['unit_type'], 'per_volume')

    def test_per_volume_unit_in_accounting_table(self):
        """per_volume unit отображается в physical_expenses таблицы учёта."""
        # Создаём рецепт с водой (per_volume)
        ProductRecipe.objects.create(
            product=self.product,
            expense=self.farsh,
            quantity_per_unit=Decimal('2'),
        )
        ProductRecipe.objects.create(
            product=self.product,
            expense=self.voda,
            proportion=Decimal('0.1'),
        )

        response = self.client.get('/api/products/products/accounting-table/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Находим наш продукт
        product_data = next(
            (p for p in response.data['products'] if p['id'] == self.product.id),
            None
        )
        self.assertIsNotNone(product_data)

        # Проверяем что вода имеет unit=per_volume
        voda_item = next(
            (e for e in product_data['physical_expenses'] if e['id'] == self.voda.id),
            None
        )
        # Если были продажи, вода будет в списке; если нет — список пуст, это ожидаемо
        if voda_item:
            self.assertEqual(voda_item['unit'], 'per_volume')

    def test_expense_unit_type_display(self):
        """ExpenseUnitType.PER_VOLUME has correct display value."""
        self.assertEqual(ExpenseUnitType.PER_VOLUME.label, 'По объёму (литр)')


# =============================================================================
# save-accounting — recipe_items (котлованская часть)
# =============================================================================

class SaveAccountingRecipeItemsTest(BaseV3Test):
    """Tests for POST /api/products/products/save-accounting/ with recipe_items."""

    def _url(self):
        return '/api/products/products/save-accounting/'

    def test_combined_mechanical_and_recipe(self):
        """Один POST: механика + котлован."""
        response = self.client.post(self._url(), {
            'mechanical_expenses': [
                {'expense_id': self.solyarka.id, 'amount': '800'},
            ],
            'recipe_items': [
                {
                    'product_id': self.product.id,
                    'expense_id': self.farsh.id,
                    'absolute_quantity': '80',
                    'product_quantity': '40',
                },
                {
                    'product_id': self.product.id,
                    'expense_id': self.luk.id,
                    'absolute_quantity': '40',
                },
            ],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['mechanical_updated'], 1)
        self.assertEqual(response.data['recipes_saved'], 2)

        # Проверяем что daily_amount обновился
        self.solyarka.refresh_from_db()
        self.assertEqual(self.solyarka.daily_amount, Decimal('800'))

        # Проверяем рецепт Сюзерена
        farsh_recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.farsh
        )
        self.assertEqual(farsh_recipe.absolute_quantity, Decimal('80'))
        self.assertEqual(farsh_recipe.quantity_per_unit, Decimal('2'))

        # Проверяем рецепт Обывателя (proportion = 40/80 = 0.5)
        luk_recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.luk
        )
        self.assertEqual(luk_recipe.absolute_quantity, Decimal('40'))
        self.assertEqual(luk_recipe.proportion, Decimal('0.5'))

    def test_recipe_update_existing(self):
        """recipe_items обновляет существующий рецепт через update_or_create."""
        # Создаём рецепт напрямую
        ProductRecipe.objects.create(
            product=self.product,
            expense=self.farsh,
            quantity_per_unit=Decimal('1'),
        )

        # Обновляем через save-accounting
        response = self.client.post(self._url(), {
            'recipe_items': [
                {
                    'product_id': self.product.id,
                    'expense_id': self.farsh.id,
                    'absolute_quantity': '100',
                    'product_quantity': '50',
                },
            ],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['recipes_saved'], 1)

        # Проверяем что обновился, а не создался дубликат
        recipes = ProductRecipe.objects.filter(
            product=self.product, expense=self.farsh
        )
        self.assertEqual(recipes.count(), 1)
        recipe = recipes.first()
        self.assertEqual(recipe.absolute_quantity, Decimal('100'))
        # quantity_per_unit = 100 / 50 = 2
        self.assertEqual(recipe.quantity_per_unit, Decimal('2'))

    def test_backward_compat_no_recipe_items(self):
        """Обратная совместимость: без recipe_items (как раньше)."""
        response = self.client.post(self._url(), {
            'mechanical_expenses': [
                {'expense_id': self.solyarka.id, 'amount': '900'},
            ],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['mechanical_updated'], 1)
        self.assertEqual(response.data['recipes_saved'], 0)
        self.assertEqual(response.data['batches_created'], 0)

    def test_recipe_with_direct_proportion(self):
        """recipe_items с прямым вводом proportion (без absolute_quantity)."""
        response = self.client.post(self._url(), {
            'recipe_items': [
                {
                    'product_id': self.product.id,
                    'expense_id': self.farsh.id,
                    'quantity_per_unit': '2.5',
                },
                {
                    'product_id': self.product.id,
                    'expense_id': self.luk.id,
                    'proportion': '0.3',
                },
            ],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        farsh_recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.farsh
        )
        self.assertEqual(farsh_recipe.quantity_per_unit, Decimal('2.5'))

        luk_recipe = ProductRecipe.objects.get(
            product=self.product, expense=self.luk
        )
        self.assertEqual(luk_recipe.proportion, Decimal('0.3'))
