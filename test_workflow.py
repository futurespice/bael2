"""
Скрипт для тестирования PartnerInventory Workflow.
Запуск: .venv/bin/python test_workflow.py
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from decimal import Decimal
from django.db import transaction
from users.models import User
from stores.models import Store, Region, City, PartnerInventory, StoreInventory
from products.models import Product
from orders.models import StoreOrder, StoreOrderItem, StoreOrderStatus
from orders.services import OrderWorkflowService, BasketService


def setup_test_data():
    """Создание тестовых данных."""
    print("\n" + "="*60)
    print("1. СОЗДАНИЕ ТЕСТОВЫХ ДАННЫХ")
    print("="*60)
    
    # Создаём админа
    admin, created = User.objects.get_or_create(
        phone='+996700000001',
        defaults={
            'email': 'admin@test.local',
            'name': 'Админ',
            'second_name': 'Тестовый',
            'role': 'admin',
            'is_staff': True,
            'is_superuser': True,
        }
    )
    if created:
        admin.set_password('admin123')
        admin.save()
    print(f"✅ Админ: {admin.phone} (ID={admin.id})")
    
    # Создаём партнёра
    partner, created = User.objects.get_or_create(
        phone='+996700000002',
        defaults={
            'email': 'partner@test.local',
            'name': 'Партнёр',
            'second_name': 'Тестовый',
            'role': 'partner',
        }
    )
    if created:
        partner.set_password('partner123')
        partner.save()
    print(f"✅ Партнёр: {partner.phone} (ID={partner.id})")
    
    # Создаём пользователя магазина
    store_user, created = User.objects.get_or_create(
        phone='+996700000003',
        defaults={
            'email': 'store@test.local',
            'name': 'Магазин',
            'second_name': 'Тестовый',
            'role': 'store',
        }
    )
    if created:
        store_user.set_password('store123')
        store_user.save()
    print(f"✅ Пользователь магазина: {store_user.phone} (ID={store_user.id})")
    
    # Создаём регион и город
    region, _ = Region.objects.get_or_create(name='Тестовый регион')
    city, _ = City.objects.get_or_create(region=region, name='Тестовый город')
    print(f"✅ Регион: {region.name}, Город: {city.name}")
    
    # Создаём магазин
    store, created = Store.objects.get_or_create(
        name='Тестовый магазин',
        defaults={
            'owner': store_user,
            'region': region,
            'city': city,
            'address': 'ул. Тестовая, 1',
            'inn': '123456789012',
            'owner_name': 'Магазин Тестовый',
            'phone': '+996555111222',
            'approval_status': 'approved',
            'is_active': True,
        }
    )
    print(f"✅ Магазин: {store.name} (ID={store.id})")
    
    # Создаём товары
    product1, _ = Product.objects.get_or_create(
        name='Мороженое тестовое',
        defaults={
            'manual_price': Decimal('100.00'),
            'stock_quantity': Decimal('1000'),
            'is_available': True,
        }
    )
    # Убедимся что цена установлена
    if product1.final_price == Decimal('0'):
        product1.manual_price = Decimal('100.00')
        product1.save()
    
    product2, _ = Product.objects.get_or_create(
        name='Сок тестовый',
        defaults={
            'manual_price': Decimal('50.00'),
            'stock_quantity': Decimal('500'),
            'is_available': True,
        }
    )
    if product2.final_price == Decimal('0'):
        product2.manual_price = Decimal('50.00')
        product2.save()
        
    print(f"✅ Товары: {product1.name} ({product1.final_price} сом), {product2.name} ({product2.final_price} сом)")
    
    # Добавляем товары в инвентарь партнёра
    inv1, _ = PartnerInventory.objects.get_or_create(
        partner=partner,
        product=product1,
        defaults={'quantity': Decimal('100'), 'reserved_quantity': Decimal('0')}
    )
    inv2, _ = PartnerInventory.objects.get_or_create(
        partner=partner,
        product=product2,
        defaults={'quantity': Decimal('50'), 'reserved_quantity': Decimal('0')}
    )
    print(f"✅ Инвентарь партнёра:")
    print(f"   - {product1.name}: quantity={inv1.quantity}, reserved={inv1.reserved_quantity}, available={inv1.available_quantity}")
    print(f"   - {product2.name}: quantity={inv2.quantity}, reserved={inv2.reserved_quantity}, available={inv2.available_quantity}")
    
    return admin, partner, store_user, store, product1, product2


def test_workflow():
    """Тестирование полного workflow."""
    admin, partner, store_user, store, product1, product2 = setup_test_data()
    
    print("\n" + "="*60)
    print("2. СОЗДАНИЕ ПРЕДЗАКАЗА МАГАЗИНОМ")
    print("="*60)
    
    # Создаём заказ напрямую (как будто магазин сделал через API)
    order = StoreOrder.objects.create(
        order_type='preorder',
        store=store,
        created_by=store_user,
        status=StoreOrderStatus.PENDING,
    )
    
    # Добавляем товары в заказ
    StoreOrderItem.objects.create(
        order=order,
        product=product1,
        quantity=Decimal('10'),
        price=product1.final_price,
    )
    StoreOrderItem.objects.create(
        order=order,
        product=product2,
        quantity=Decimal('5'),
        price=product2.final_price,
    )
    
    order.calculate_total()
    order.save()
    print(f"✅ Создан заказ #{order.id}")
    print(f"   Статус: {order.get_status_display()}")
    print(f"   Сумма: {order.total_amount} сом")
    for item in order.items.all():
        print(f"   - {item.product.name} x{item.quantity}")
    
    print("\n" + "="*60)
    print("3. APPROVE ЗАКАЗА ПАРТНЁРОМ")
    print("="*60)
    
    # Проверяем инвентарь до
    inv1 = PartnerInventory.objects.get(partner=partner, product=product1)
    inv2 = PartnerInventory.objects.get(partner=partner, product=product2)
    print(f"📦 Инвентарь ДО approve:")
    print(f"   - {product1.name}: quantity={inv1.quantity}, reserved={inv1.reserved_quantity}, available={inv1.available_quantity}")
    print(f"   - {product2.name}: quantity={inv2.quantity}, reserved={inv2.reserved_quantity}, available={inv2.available_quantity}")
    
    try:
        order = OrderWorkflowService.admin_approve_order(
            order=order,
            admin_user=partner,  # Партнёр сам принимает
            assign_to_partner=None,
        )
        print(f"\n✅ Заказ одобрен!")
        print(f"   Статус: {order.get_status_display()}")
        print(f"   Партнёр: {order.partner.get_full_name()}")
    except Exception as e:
        print(f"\n❌ Ошибка при approve: {e}")
        return
    
    # Проверяем инвентарь после
    inv1.refresh_from_db()
    inv2.refresh_from_db()
    print(f"\n📦 Инвентарь ПОСЛЕ approve:")
    print(f"   - {product1.name}: quantity={inv1.quantity}, reserved={inv1.reserved_quantity}, available={inv1.available_quantity}")
    print(f"   - {product2.name}: quantity={inv2.quantity}, reserved={inv2.reserved_quantity}, available={inv2.available_quantity}")
    
    print("\n" + "="*60)
    print("4. CONFIRM КОРЗИНЫ ПАРТНЁРОМ")
    print("="*60)
    
    try:
        result = BasketService.confirm_basket(
            store=store,
            partner_user=partner,
            prepayment_amount=Decimal('500'),
        )
        print(f"\n✅ Корзина подтверждена!")
        print(f"   Заказов: {len(result['confirmed_orders'])}")
        print(f"   Общая сумма: {result['totals']['total_amount']} сом")
        print(f"   Предоплата: {result['totals']['prepayment']} сом")
        print(f"   Долг: {result['totals']['debt_created']} сом")
    except Exception as e:
        print(f"\n❌ Ошибка при confirm: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Проверяем инвентарь партнёра после
    print(f"\n📦 Инвентарь партнёра ПОСЛЕ confirm:")
    try:
        inv1.refresh_from_db()
        print(f"   - {product1.name}: quantity={inv1.quantity}, reserved={inv1.reserved_quantity}")
    except PartnerInventory.DoesNotExist:
        print(f"   - {product1.name}: УДАЛЁН (quantity=0)")
    try:
        inv2.refresh_from_db()
        print(f"   - {product2.name}: quantity={inv2.quantity}, reserved={inv2.reserved_quantity}")
    except PartnerInventory.DoesNotExist:
        print(f"   - {product2.name}: УДАЛЁН (quantity=0)")
    
    # Проверяем инвентарь магазина
    print(f"\n📦 Инвентарь МАГАЗИНА:")
    store_inv = StoreInventory.objects.filter(store=store)
    for inv in store_inv:
        print(f"   - {inv.product.name}: quantity={inv.quantity}")
    
    # Проверяем статус заказа
    order.refresh_from_db()
    print(f"\n📦 Заказ #{order.id}:")
    print(f"   Статус: {order.get_status_display()}")
    print(f"   Предоплата: {order.prepayment_amount} сом")
    print(f"   Долг: {order.debt_amount} сом")
    
    print("\n" + "="*60)
    print("✅ ТЕСТ ЗАВЕРШЁН УСПЕШНО!")
    print("="*60)


if __name__ == '__main__':
    test_workflow()
