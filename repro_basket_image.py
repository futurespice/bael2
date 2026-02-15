
import os
import django
from decimal import Decimal
import io

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from users.models import User
from stores.models import Store, Region, City
from products.models import Product, ProductImage
from orders.models import StoreOrder, StoreOrderItem, StoreOrderStatus
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from stores.views import StoreViewSet
from rest_framework.test import force_authenticate

def run():
    print("Setting up test data...")
    
    # Create User
    try:
        user = User.objects.get(email='test_partner_basket@example.com')
    except User.DoesNotExist:
        user = User.objects.create(
            email='test_partner_basket@example.com',
            phone='+996700111999',
            name='Test Partner Basket',
            role='partner'
        )
        user.set_password('password')
        user.save()
    
    # Create Store
    region, _ = Region.objects.get_or_create(name='Test Region Basket')
    city, _ = City.objects.get_or_create(region=region, name='Test City Basket')
    store, _ = Store.objects.get_or_create(
        inn='999999999999',
        defaults={
            'name': 'Test Store Basket',
            'owner': user,
            'region': region,
            'city': city,
            'address': 'Test Address',
            'phone': '+996555111999'
        }
    )
    
    # Create Product with Image
    product, _ = Product.objects.get_or_create(
        name='Test Product Basket Image',
        defaults={
            'manual_price': Decimal('100.00'),
            'stock_quantity': Decimal('100'),
            'is_weight_based': False
        }
    )
    
    # Create Image if not exists
    if not ProductImage.objects.filter(product=product).exists():
        # Minimal valid JPEG
        image_content = b'\xff\xd8\xff\xe0\x00\x10\x4a\x46\x49\x46\x00\x01\x01\x01\x00\x48\x00\x48\x00\x00\xff\xdb\x00\x43\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xbf\xff\xd9'
        uploaded_image = SimpleUploadedFile(name='test_image_basket.jpg', content=image_content, content_type='image/jpeg')
        ProductImage.objects.create(product=product, image=uploaded_image)
        print("Created product image")
    else:
        print("Product image already exists")

    # Create Order in IN_TRANSIT
    # Ensure no existing IN_TRANSIT orders for this store to clean state
    StoreOrder.objects.filter(store=store, status=StoreOrderStatus.IN_TRANSIT).delete()

    order = StoreOrder.objects.create(
        store=store,
        status=StoreOrderStatus.IN_TRANSIT,
        created_by=user,
        order_type='preorder'
    )
    
    StoreOrderItem.objects.create(
        order=order,
        product=product,
        quantity=Decimal('10'),
        price=product.final_price,
        total=product.final_price * Decimal('10')
    )
    
    print("Created order in IN_TRANSIT")
    
    # Simulate View
    factory = RequestFactory()
    request = factory.get(f'/api/stores/{store.id}/basket/')
    force_authenticate(request, user=user)
    request.user = user # Ensure user is attached
    
    # Because it's a ViewSet action, we need to initialize it properly
    view = StoreViewSet.as_view({'get': 'basket'})
    response = view(request, pk=store.id)
    
    print(f"Response status: {response.status_code}")
    if response.status_code == 200:
        data = response.data
        if 'items' in data:
            items = data['items']
            print(f"Found {len(items)} items in basket")
            for item in items:
                print(f"Product: {item['product_name']}")
                print(f"Image URL: {item['product_image']}")
                
                if item['product_image']:
                    print("SUCCESS: Image URL is present")
                else:
                    print("FAILURE: Image URL is missing")
        else:
             print("FAILURE: 'items' key missing in response")
             print(data)

    else:
        print(f"Error: {response.data}")

if __name__ == '__main__':
    run()
