from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from products.models import Product, Expense, ExpenseType, ExpenseStatus, ProductRecipe, ProductImage
from users.models import User
from decimal import Decimal

class ProductAPIFixTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Create user and authenticate
        self.user = User.objects.create(
            phone='+996555123456', 
            email='test@example.com', 
            name='Test', 
            second_name='Admin',
            role='admin',
            is_active=True
        )
        self.client.force_authenticate(user=self.user)
        
        # Create expenses
        self.expense1 = Expense.objects.create(
            name='Suzerain Expense', 
            expense_type=ExpenseType.PHYSICAL, 
            expense_status=ExpenseStatus.SUZERAIN,
            price_per_unit=100,
            unit_type='kg'
        )
        self.expense2 = Expense.objects.create(
            name='Civilian Expense', 
            expense_type=ExpenseType.PHYSICAL, 
            expense_status=ExpenseStatus.CIVILIAN,
            price_per_unit=50,
            unit_type='piece'
        )

    def test_create_product_with_indexed_recipes_and_images(self):
        print("\n--- TEST: Create Product with indexed recipes and images ---")
        # Valid 1x1 GIF
        valid_image_content = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x01\x44\x00\x3b'
        image = SimpleUploadedFile("test_image.gif", valid_image_content, content_type="image/gif")
        
        data = {
            'name': 'Test Dumplings',
            'unit': 'kg',
            'is_weight_based': 'true',
            'images': [image],
            
            # Indexed fields similar to Kotlin client for Suzerain
            'recipe_items[0][expense]': self.expense1.id,
            'recipe_items[0][quantity_per_unit]': '0.5',
            # 'recipe_items[0][proportion]': '1.0', # Suzerain often doesn't need proportion or it's implicitly 1
            
            # Second item (Civilian)
            'recipe_items[1][expense]': self.expense2.id,
            'recipe_items[1][proportion]': '0.2',
        }
        
        response = self.client.post('/api/products/products/', data, format='multipart')
        
        if response.status_code != 201:
            print(f"Error response: {response.data}")
            
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        product_id = response.data['id']
        product = Product.objects.get(id=product_id)
        
        # Check Product
        self.assertEqual(product.name, 'Test Dumplings')
        
        # Check Images
        self.assertEqual(product.images.count(), 1)
        # Check Recipes
        self.assertEqual(ProductRecipe.objects.count(), 2)
        recipe1 = ProductRecipe.objects.get(product=product, expense=self.expense1)
        self.assertEqual(recipe1.quantity_per_unit, Decimal('0.50'))
        
        recipe2 = ProductRecipe.objects.get(product=product, expense=self.expense2)
        self.assertEqual(recipe2.proportion, Decimal('0.20'))
        print("SUCCESS: Product created with images and recipes.")
        
        return product

    def test_update_product_append_images_and_clear_recipes(self):
        print("\n--- TEST: Update Product (append image, clear recipes) ---")
        # 1. Create initial product
        product = Product.objects.create(name='Original Name', unit='kg')
        ProductImage.objects.create(product=product, image='old.jpg', order=0)
        ProductRecipe.objects.create(product=product, expense=self.expense1, quantity_per_unit=1)
        
        self.assertEqual(product.images.count(), 1)
        self.assertEqual(ProductRecipe.objects.count(), 1)
        
        # 2. Update via PUT (simulating Kotlin client)
        valid_image_content = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x01\x44\x00\x3b'
        image_new = SimpleUploadedFile("new.gif", valid_image_content, content_type="image/gif")
        
        data = {
            'name': 'Updated Name',
            'unit': 'kg',
            'images': [image_new],
            'recipe_items': '[]' # Kotlin client sends this string to clear recipes
        }
        
        response = self.client.put(f'/api/products/products/{product.id}/', data, format='multipart')
        
        if response.status_code != 200:
            print(f"Error response: {response.data}")
            
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        product.refresh_from_db()
        # Name updated
        self.assertEqual(product.name, 'Updated Name')
        
        # Images APPENDED (should be 2: old + new)
        self.assertEqual(product.images.count(), 2)
        
        # Recipes CLEARED
        self.assertEqual(ProductRecipe.objects.filter(product=product).count(), 0)
        print("SUCCESS: Product updated, image appended, recipes cleared.")

    def test_update_product_with_indexed_recipes(self):
        print("\n--- TEST: Update Product with indexed recipes ---")
        product = Product.objects.create(name='Product 3', unit='kg')
        
        data = {
            'name': 'Product 3',
            'unit': 'kg',
            # Sending new recipes via indexed fields
            'recipe_items[0][expense]': self.expense1.id,
            'recipe_items[0][quantity_per_unit]': '1.5'
        }
        
        response = self.client.patch(f'/api/products/products/{product.id}/', data, format='multipart')
        if response.status_code != 200:
             print(f"Error: {response.data}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.assertEqual(ProductRecipe.objects.count(), 1)
        recipe = ProductRecipe.objects.first()
        self.assertEqual(recipe.quantity_per_unit, Decimal('1.50'))
        print("SUCCESS: Product updated with indexed recipes.")
