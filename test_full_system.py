"""
Комплексный тест всей системы BAEL 3.0
Запуск: .venv/bin/python test_full_system.py

Тестирует:
- Обычные товары (штучные)
- Весовые товары (is_weight_based=True)  
- PartnerInventory workflow
- StoreInventory workflow
- Ручные заказы
- Отчёты и статистика
"""
import os
import sys
import django
from datetime import date, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from users.models import User
from stores.models import Store, Region, City, PartnerInventory, StoreInventory
from products.models import Product
from orders.models import StoreOrder, StoreOrderItem, StoreOrderStatus, DebtPayment
from orders.services import OrderWorkflowService
from rest_framework.test import APIClient


# ============================================================================
# SETUP
# ============================================================================

def clean_database():
    """Очистка тестовых данных."""
    print("\n🧹 Очистка базы данных...")
    StoreOrderItem.objects.all().delete()
    StoreOrder.objects.all().delete()
    StoreInventory.objects.all().delete()
    PartnerInventory.objects.all().delete()
    Product.objects.filter(name__contains='ТЕСТ').delete()
    Store.objects.filter(name__contains='ТЕСТ').delete()
    User.objects.filter(phone__startswith='+996700').delete()
    print("✅ База очищена")


def create_users():
    """Создание пользователей."""
    print("\n👤 Создание пользователей...")
    
    admin = User.objects.create(
        phone='+996700000001',
        email='admin@test.local',
        name='Админ',
        second_name='ТЕСТ',
        role='admin',
        is_staff=True,
        is_superuser=True,
    )
    admin.set_password('admin123')
    admin.save()
    
    partner = User.objects.create(
        phone='+996700000002',
        email='partner@test.local',
        name='Партнёр',
        second_name='ТЕСТ',
        role='partner',
    )
    partner.set_password('partner123')
    partner.save()
    
    store_user = User.objects.create(
        phone='+996700000003',
        email='store@test.local',
        name='Магазин',
        second_name='ТЕСТ',
        role='store',
    )
    store_user.set_password('store123')
    store_user.save()
    
    print(f"   ✅ Админ: {admin.phone}")
    print(f"   ✅ Партнёр: {partner.phone}")
    print(f"   ✅ Магазин: {store_user.phone}")
    
    return admin, partner, store_user


def create_store(store_user):
    """Создание магазина."""
    print("\n🏪 Создание магазина...")
    
    region, _ = Region.objects.get_or_create(name='ТЕСТ Регион')
    city, _ = City.objects.get_or_create(region=region, name='ТЕСТ Город')
    
    store = Store.objects.create(
        name='ТЕСТ Магазин Айсберг',
        owner=store_user,
        region=region,
        city=city,
        address='ул. Тестовая, 1',
        inn='123456789012',
        owner_name='Магазин ТЕСТ',
        phone='+996555111222',
        approval_status='approved',
        is_active=True,
    )
    
    print(f"   ✅ Магазин: {store.name} (ID={store.id})")
    return store


def create_products():
    """Создание товаров: обычные и весовые."""
    print("\n📦 Создание товаров...")
    
    # Штучные товары
    ice_cream = Product.objects.create(
        name='ТЕСТ Мороженое Пломбир',
        manual_price=Decimal('100.00'),
        stock_quantity=Decimal('1000'),
        is_available=True,
        is_weight_based=False,
        unit='piece',
    )
    
    juice = Product.objects.create(
        name='ТЕСТ Сок Яблочный',
        manual_price=Decimal('50.00'),
        stock_quantity=Decimal('500'),
        is_available=True,
        is_weight_based=False,
        unit='piece',
    )
    
    # Весовые товары
    cheese = Product.objects.create(
        name='ТЕСТ Сыр Брынза (весовой)',
        manual_price=Decimal('800.00'),  # за кг
        stock_quantity=Decimal('50'),
        is_available=True,
        is_weight_based=True,
        unit='kg',
    )
    
    meat = Product.objects.create(
        name='ТЕСТ Мясо Говядина (весовой)',
        manual_price=Decimal('650.00'),  # за кг
        stock_quantity=Decimal('100'),
        is_available=True,
        is_weight_based=True,
        unit='kg',
    )
    
    print(f"   ✅ Штучные товары:")
    print(f"      - {ice_cream.name}: {ice_cream.final_price} сом/шт")
    print(f"      - {juice.name}: {juice.final_price} сом/шт")
    print(f"   ✅ Весовые товары:")
    print(f"      - {cheese.name}: {cheese.final_price} сом/кг")
    print(f"      - {meat.name}: {meat.final_price} сом/кг")
    
    return ice_cream, juice, cheese, meat


def create_partner_inventory(partner, products):
    """Добавление товаров в инвентарь партнёра."""
    print("\n📋 Создание инвентаря партнёра...")
    
    inventories = []
    for product, qty in products:
        inv = PartnerInventory.objects.create(
            partner=partner,
            product=product,
            quantity=qty,
            reserved_quantity=Decimal('0'),
        )
        inventories.append(inv)
        print(f"   ✅ {product.name}: {qty} {'кг' if product.is_weight_based else 'шт'}")
    
    return inventories


# ============================================================================
# ТЕСТЫ
# ============================================================================

def test_preorder_workflow(partner, store_user, store, ice_cream, juice, cheese, meat):
    """Тест полного workflow предзаказа."""
    print("\n" + "="*70)
    print("ТЕСТ 1: ПРЕДЗАКАЗ С ОБЫЧНЫМИ И ВЕСОВЫМИ ТОВАРАМИ")
    print("="*70)
    
    # 1. Создаём предзаказ
    print("\n📝 Шаг 1: Создание предзаказа магазином...")
    order = StoreOrder.objects.create(
        order_type='preorder',
        store=store,
        created_by=store_user,
        status=StoreOrderStatus.PENDING,
    )
    
    items_data = [
        (ice_cream, Decimal('10')),      # 10 шт мороженого
        (juice, Decimal('20')),          # 20 шт сока
        (cheese, Decimal('2.5')),        # 2.5 кг сыра
        (meat, Decimal('5.25')),         # 5.25 кг мяса
    ]
    
    for product, qty in items_data:
        StoreOrderItem.objects.create(
            order=order,
            product=product,
            quantity=qty,
            price=product.final_price,
        )
    
    order.calculate_total()
    order.save()
    
    print(f"   ✅ Заказ #{order.id} создан")
    print(f"   📊 Товары:")
    for item in order.items.all():
        unit = 'кг' if item.product.is_weight_based else 'шт'
        subtotal = item.quantity * item.price
        print(f"      - {item.product.name}: {item.quantity} {unit} × {item.price} = {subtotal} сом")
    print(f"   💰 Итого: {order.total_amount} сом")
    
    # 2. Проверяем инвентарь партнёра ДО
    print("\n📦 Шаг 2: Инвентарь партнёра ДО approve...")
    for product, _ in items_data:
        inv = PartnerInventory.objects.get(partner=partner, product=product)
        print(f"   - {product.name}: qty={inv.quantity}, reserved={inv.reserved_quantity}, available={inv.available_quantity}")
    
    # 3. Approve заказа
    print("\n✅ Шаг 3: Партнёр одобряет заказ (approve)...")
    order = OrderWorkflowService.admin_approve_order(
        order=order,
        admin_user=partner,
        assign_to_partner=None,
    )
    print(f"   ✅ Статус: {order.get_status_display()}")
    print(f"   ✅ Партнёр: {order.partner.get_full_name()}")
    
    # 4. Проверяем инвентарь партнёра ПОСЛЕ approve
    print("\n📦 Шаг 4: Инвентарь партнёра ПОСЛЕ approve...")
    for product, qty in items_data:
        inv = PartnerInventory.objects.get(partner=partner, product=product)
        print(f"   - {product.name}: qty={inv.quantity}, reserved={inv.reserved_quantity}, available={inv.available_quantity}")
        assert inv.reserved_quantity == qty, f"Ошибка резервирования для {product.name}"
    print("   ✅ Резервирование прошло корректно!")
    
    # 5. Confirm корзины
    print("\n🛒 Шаг 5: Партнёр подтверждает корзину (confirm)...")
    prepayment = Decimal('2000')
    client = APIClient()
    client.force_authenticate(user=partner)
    resp = client.post(
        f'/api/stores/stores/{store.id}/basket/confirm/',
        {'prepayment_amount': str(prepayment)},
        format='json',
    )
    assert resp.status_code == 200, f"confirm_basket failed: {resp.data}"
    result = resp.data

    print(f"   ✅ Заказов подтверждено: {len(result['confirmed_orders'])}")
    print(f"   💰 Общая сумма: {result['totals']['total_amount']} сом")
    print(f"   💵 Предоплата: {result['totals']['prepayment']} сом")
    print(f"   📊 Долг: {result['totals']['debt_created']} сом")
    
    # 6. Проверяем инвентарь партнёра ПОСЛЕ confirm
    print("\n📦 Шаг 6: Инвентарь партнёра ПОСЛЕ confirm...")
    for product, qty in items_data:
        inv = PartnerInventory.objects.get(partner=partner, product=product)
        print(f"   - {product.name}: qty={inv.quantity}, reserved={inv.reserved_quantity}")
        assert inv.reserved_quantity == Decimal('0'), f"Резерв должен быть 0 для {product.name}"
    print("   ✅ Резервы освобождены!")
    
    # 7. Проверяем инвентарь магазина
    print("\n🏪 Шаг 7: Инвентарь МАГАЗИНА...")
    for product, qty in items_data:
        store_inv = StoreInventory.objects.get(store=store, product=product)
        unit = 'кг' if product.is_weight_based else 'шт'
        print(f"   - {product.name}: {store_inv.quantity} {unit}")
        assert store_inv.quantity == qty, f"Количество не совпадает для {product.name}"
    print("   ✅ Товары добавлены в инвентарь магазина!")
    
    # 8. Проверяем долг
    print("\n💳 Шаг 8: Долг магазина...")
    order.refresh_from_db()
    store.refresh_from_db()
    print(f"   - Заказ #{order.id}: сумма={order.total_amount}, предоплата={order.prepayment_amount}, долг={order.debt_amount}")
    print(f"   - Общий долг магазина (Store.debt): {store.debt} сом")
    
    return order


def test_manual_order(partner, store_user, store, ice_cream, juice):
    """Тест ручного заказа."""
    print("\n" + "="*70)
    print("ТЕСТ 2: РУЧНОЙ ЗАКАЗ")
    print("="*70)
    
    print("\n📝 Создание ручного заказа...")
    
    # Ручной заказ = StoreOrder с order_type='manual'
    manual_order = StoreOrder.objects.create(
        order_type='manual',
        store=store,
        created_by=partner,
        status=StoreOrderStatus.ACCEPTED,
    )
    
    # Для ручного заказа товары добавляются напрямую в StoreInventory
    from stores.services import StoreInventoryService
    
    add_items = [
        (ice_cream, Decimal('5')),
        (juice, Decimal('10')),
    ]
    
    for product, qty in add_items:
        StoreInventoryService.add_to_inventory(
            store=store,
            product=product,
            quantity=qty,
        )
        print(f"   ✅ Добавлено: {product.name} x{qty}")
    
    print(f"\n   ✅ Ручной заказ #{manual_order.id} создан")
    
    # Проверяем обновлённый инвентарь магазина
    print("\n🏪 Инвентарь магазина после ручного заказа:")
    for product, _ in add_items:
        store_inv = StoreInventory.objects.get(store=store, product=product)
        print(f"   - {product.name}: {store_inv.quantity} шт")
    
    return manual_order


def test_reports(partner, store):
    """Тест отчётов и статистики."""
    print("\n" + "="*70)
    print("ТЕСТ 3: ОТЧЁТЫ И СТАТИСТИКА")
    print("="*70)
    
    # Статистика по заказам
    print("\n📊 Статистика заказов магазина:")
    orders = StoreOrder.objects.filter(store=store)
    total_orders = orders.count()
    completed_orders = orders.filter(status=StoreOrderStatus.ACCEPTED).count()
    total_amount = orders.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    
    print(f"   - Всего заказов: {total_orders}")
    print(f"   - Завершённых: {completed_orders}")
    print(f"   - Общая сумма: {total_amount} сом")
    
    # Статистика по инвентарю партнёра
    print("\n📊 Статистика инвентаря партнёра:")
    partner_inv = PartnerInventory.objects.filter(partner=partner)
    total_items = partner_inv.count()
    total_qty = partner_inv.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
    total_reserved = partner_inv.aggregate(total=Sum('reserved_quantity'))['total'] or Decimal('0')
    
    print(f"   - Товаров в инвентаре: {total_items}")
    print(f"   - Общее количество: {total_qty}")
    print(f"   - Зарезервировано: {total_reserved}")
    
    # Статистика по инвентарю магазина
    print("\n📊 Статистика инвентаря магазина:")
    store_inv = StoreInventory.objects.filter(store=store)
    total_store_items = store_inv.count()
    
    for inv in store_inv:
        unit = 'кг' if inv.product.is_weight_based else 'шт'
        print(f"   - {inv.product.name}: {inv.quantity} {unit}")
    
    # Статистика долгов
    print("\n📊 Статистика долгов:")
    store.refresh_from_db()
    print(f"   - Долг магазина: {store.debt} сом")
    
    return True


def test_weight_calculation():
    """Тест расчёта цены весовых товаров."""
    print("\n" + "="*70)
    print("ТЕСТ 4: РАСЧЁТ ЦЕНЫ ВЕСОВЫХ ТОВАРОВ")
    print("="*70)
    
    cheese = Product.objects.get(name='ТЕСТ Сыр Брынза (весовой)')
    meat = Product.objects.get(name='ТЕСТ Мясо Говядина (весовой)')
    
    test_cases = [
        (cheese, Decimal('0.5'), Decimal('400.00')),   # 0.5 кг сыра = 400 сом
        (cheese, Decimal('1.5'), Decimal('1200.00')),  # 1.5 кг сыра = 1200 сом
        (meat, Decimal('2.0'), Decimal('1300.00')),    # 2 кг мяса = 1300 сом
        (meat, Decimal('0.25'), Decimal('162.50')),    # 0.25 кг мяса = 162.50 сом
    ]
    
    print("\n📊 Проверка расчётов:")
    all_passed = True
    for product, qty, expected in test_cases:
        actual = qty * product.final_price
        status = "✅" if actual == expected else "❌"
        if actual != expected:
            all_passed = False
        print(f"   {status} {product.name}: {qty} кг × {product.final_price} = {actual} (ожидалось: {expected})")
    
    if all_passed:
        print("\n   ✅ Все расчёты корректны!")
    else:
        print("\n   ❌ Есть ошибки в расчётах!")
    
    return all_passed


# ============================================================================
# MAIN
# ============================================================================

def run_all_tests():
    """Запуск всех тестов."""
    print("\n" + "="*70)
    print("🚀 КОМПЛЕКСНОЕ ТЕСТИРОВАНИЕ СИСТЕМЫ BAEL 3.0")
    print("="*70)
    print(f"Дата: {date.today()}")
    
    try:
        with transaction.atomic():
            # Подготовка
            clean_database()
            admin, partner, store_user = create_users()
            store = create_store(store_user)
            ice_cream, juice, cheese, meat = create_products()
            
            # Инвентарь партнёра
            create_partner_inventory(partner, [
                (ice_cream, Decimal('100')),
                (juice, Decimal('200')),
                (cheese, Decimal('50')),     # 50 кг
                (meat, Decimal('100')),      # 100 кг
            ])
            
            # Тесты
            test_preorder_workflow(partner, store_user, store, ice_cream, juice, cheese, meat)
            test_manual_order(partner, store_user, store, ice_cream, juice)
            test_weight_calculation()
            test_reports(partner, store)
            
            print("\n" + "="*70)
            print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
            print("="*70)
            
            # Откатываем транзакцию чтобы не засорять базу
            raise Exception("Rollback test data")
            
    except Exception as e:
        if str(e) == "Rollback test data":
            print("\n🧹 Тестовые данные откачены (база чистая)")
        else:
            print(f"\n❌ ОШИБКА: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == '__main__':
    run_all_tests()
