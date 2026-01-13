from django.db import migrations
from django.db.models import Q


def set_default_owners(apps, schema_editor):
    """
    Установить owner для всех магазинов.
    
    ЛОГИКА:
    1. Если у магазина есть created_by → owner = created_by
    2. Иначе → owner = первый админ
    3. Логировать все изменения
    """
    Store = apps.get_model('stores', 'Store')
    User = apps.get_model('users', 'User')  # Предполагаем, что модель пользователя в приложении users
    
    # Получить первого админа (fallback)
    # Используем role='admin' если она есть, иначе is_staff=True
    admin = User.objects.filter(role='admin').first()
    if not admin:
        print("\n⚠️ ВНИМАНИЕ: Не найден пользователь с role='admin'. Ищем is_superuser=True...")
        admin = User.objects.filter(is_superuser=True).first()
        
    if not admin:
        print("⚠️ ОШИБКА: Не найден ни один админ! Магазины без created_by останутся без owner.")
        # Тут можно либо прервать, либо продолжить. Продолжим, но owner останется NULL.
    else:
        print(f"✅ Используем админа для fallback: {admin.id} ({getattr(admin, 'email', 'unknown')})")
    
    # Обработать магазины без owner
    stores_without_owner = Store.objects.filter(owner__isnull=True)
    total = stores_without_owner.count()
    
    print(f"📊 Найдено магазинов без owner: {total}")
    
    updated_count = 0
    for store in stores_without_owner:
        new_owner = None
        
        # Попытка 1: Использовать created_by
        if hasattr(store, 'created_by') and store.created_by:
            new_owner = store.created_by
            # print(f"✅ Магазин #{store.id} '{store.name}': owner = {new_owner.id} (created_by)")
        else:
            # Попытка 2: Использовать админа
            if admin:
                new_owner = admin
                # print(f"⚠️ Магазин #{store.id} '{store.name}': owner = {new_owner.id} (fallback на админа)")
            else:
                print(f"❌ Магазин #{store.id} '{store.name}': Не удалось установить owner")
        
        if new_owner:
            store.owner = new_owner
            store.save(update_fields=['owner'])
            updated_count += 1
    
    print(f"✅ Обновлено магазинов: {updated_count}/{total}")


def reverse_migration(apps, schema_editor):
    """Откат миграции - установить owner = NULL."""
    Store = apps.get_model('stores', 'Store')
    Store.objects.all().update(owner=None)
    print("⚠️ Откат: owner установлен в NULL для всех магазинов")


class Migration(migrations.Migration):
    
    dependencies = [
        ('stores', '0004_add_owner_nullable'),
    ]
    
    operations = [
        migrations.RunPython(set_default_owners, reverse_migration),
    ]
