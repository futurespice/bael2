# stores/migrations/0009_cleanup_storeselection_duplicates.py
"""
Миграция для очистки дублирующихся записей StoreSelection.

Проблема: У некоторых пользователей есть несколько записей,
что вызывает ошибку MultipleObjectsReturned.

Решение: Оставить только одну активную запись на пользователя.
"""

from django.db import migrations


def cleanup_duplicates(apps, schema_editor):
    """
    Очистка дублирующихся записей StoreSelection.
    
    Логика:
    1. Найти пользователей с несколькими записями
    2. Для каждого пользователя оставить только одну запись:
       - Приоритет: is_current=True
       - Иначе: самая свежая по selected_at
    3. Остальные записи удалить
    """
    StoreSelection = apps.get_model('stores', 'StoreSelection')
    
    from django.db.models import Count
    
    # Найти пользователей с дубликатами
    users_with_duplicates = (
        StoreSelection.objects
        .values('user_id')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
    )
    
    total_deleted = 0
    
    for item in users_with_duplicates:
        user_id = item['user_id']
        
        # Получить все записи пользователя
        selections = StoreSelection.objects.filter(user_id=user_id).order_by('-selected_at')
        
        # Найти запись для сохранения (приоритет: is_current=True, иначе самая свежая)
        active_selection = selections.filter(is_current=True).first()
        if not active_selection:
            active_selection = selections.first()
        
        # Удалить все кроме выбранной
        to_delete = selections.exclude(id=active_selection.id)
        delete_count = to_delete.count()
        to_delete.delete()
        
        # Убедиться что оставшаяся запись активна
        if not active_selection.is_current:
            active_selection.is_current = True
            active_selection.save(update_fields=['is_current'])
        
        total_deleted += delete_count
    
    if total_deleted > 0:
        print(f'\n✅ Очистка StoreSelection: удалено {total_deleted} дублирующихся записей')
    else:
        print('\n✅ Дубликатов StoreSelection не найдено')


def reverse_cleanup(apps, schema_editor):
    """Обратная миграция не требуется."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('stores', '0008_add_partner_request_link'),
    ]

    operations = [
        migrations.RunPython(cleanup_duplicates, reverse_cleanup),
    ]
