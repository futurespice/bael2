"""
Миграция данных: исправление quantity_per_unit у Сюзеренов в рецептах.

Проблема: в ProductRecipe для Сюзеренов поля quantity_per_unit и proportion
были сохранены в перевёрнутом виде:
  quantity_per_unit = 1.0  (должно быть реальное количество, напр. 0.22)
  proportion = 0.22        (должно быть 1.0, так как Сюзерен = 100% от себя)

Исправление: если quantity_per_unit=1.0 И proportion IN (0, 1) исключая 1.0 —
меняем местами: quantity_per_unit берём из proportion, proportion = 1.0
"""

from django.db import migrations


def fix_suzerain_quantity_per_unit(apps, schema_editor):
    ProductRecipe = apps.get_model('products', 'ProductRecipe')

    # Ищем все рецепты Сюзеренов где данные перепутаны:
    # quantity_per_unit = 1.0 (явно неверно для ингредиента на пачку)
    # proportion != null и proportion < 1.0 (пропорция хранит реальную норму)
    wrong_suzerain_recipes = ProductRecipe.objects.filter(
        expense__expense_status='suzerain',
        quantity_per_unit=1.0,
        proportion__isnull=False,
        proportion__lt=1.0,
        proportion__gt=0,
    )

    fixed_count = 0
    for recipe in wrong_suzerain_recipes:
        real_qty_per_unit = recipe.proportion  # реальная норма была в proportion
        recipe.quantity_per_unit = real_qty_per_unit
        recipe.proportion = None  # Сюзерен — это база, proportion не используется
        recipe.save()
        fixed_count += 1

    if fixed_count:
        print(f"\nИсправлено {fixed_count} рецептов Сюзеренов (quantity_per_unit ↔ proportion)")


def reverse_fix(apps, schema_editor):
    """Откат: возвращаем quantity_per_unit=1.0 и proportion=реальное_значение."""
    # Обратный откат невозможен без хранения оригиналов,
    # поэтому откат не реализован (возможен ручной сброс через API).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0009_expense_name_unique'),
    ]

    operations = [
        migrations.RunPython(fix_suzerain_quantity_per_unit, reverse_fix),
    ]
