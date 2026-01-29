# stores/management/commands/cleanup_store_selections.py
"""
Команда для очистки дублирующихся записей StoreSelection.

Проблема: У некоторых пользователей есть несколько записей в StoreSelection,
что вызывает ошибку MultipleObjectsReturned при вызове get().

Решение: Оставить только последнюю активную запись (is_current=True),
остальные удалить.

Использование:
    python manage.py cleanup_store_selections --dry-run  # Предварительный просмотр
    python manage.py cleanup_store_selections            # Реальная очистка
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from stores.models import StoreSelection


class Command(BaseCommand):
    help = 'Очистка дублирующихся записей StoreSelection'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показать что будет удалено без реального удаления',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        self.stdout.write(self.style.WARNING(
            '=' * 60 + '\n'
            'Очистка дублирующихся записей StoreSelection\n'
            '=' * 60
        ))

        if dry_run:
            self.stdout.write(self.style.WARNING('РЕЖИМ ПРОСМОТРА (dry-run)\n'))

        # Найти пользователей с дубликатами
        users_with_duplicates = (
            StoreSelection.objects
            .values('user')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        if not users_with_duplicates:
            self.stdout.write(self.style.SUCCESS('✅ Дубликатов не найдено!'))
            return

        self.stdout.write(f'Найдено пользователей с дубликатами: {len(users_with_duplicates)}\n')

        total_deleted = 0

        with transaction.atomic():
            for item in users_with_duplicates:
                user_id = item['user']
                count = item['count']

                self.stdout.write(f'\n👤 User ID: {user_id} - {count} записей')

                # Получить все записи пользователя
                selections = StoreSelection.objects.filter(user_id=user_id).order_by('-selected_at')

                # Показать все записи
                for sel in selections:
                    status = "✅ ТЕКУЩИЙ" if sel.is_current else "❌ неактивный"
                    self.stdout.write(
                        f'   - ID: {sel.id}, Store: {sel.store.name}, '
                        f'{status}, selected_at: {sel.selected_at}'
                    )

                # Определить какую запись оставить
                # Приоритет: is_current=True, иначе самая свежая
                active_selection = selections.filter(is_current=True).first()
                
                if not active_selection:
                    # Если нет активной - берём самую свежую
                    active_selection = selections.first()
                    self.stdout.write(
                        f'   ⚠️ Нет активной записи, выбираем самую свежую: ID {active_selection.id}'
                    )

                # Удалить все кроме выбранной
                to_delete = selections.exclude(id=active_selection.id)
                delete_count = to_delete.count()

                self.stdout.write(
                    f'   🗑️ Будет удалено: {delete_count} записей, '
                    f'останется: ID {active_selection.id} (Store: {active_selection.store.name})'
                )

                if not dry_run:
                    # Удаляем дубликаты
                    to_delete.delete()
                    
                    # Убедимся что оставшаяся запись активна
                    if not active_selection.is_current:
                        active_selection.is_current = True
                        active_selection.save(update_fields=['is_current'])
                        self.stdout.write(f'   ✅ Запись ID {active_selection.id} сделана активной')

                total_deleted += delete_count

        # Итоги
        self.stdout.write('\n' + '=' * 60)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'РЕЖИМ ПРОСМОТРА: было бы удалено {total_deleted} записей\n'
                'Запустите без --dry-run для реальной очистки'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'✅ Удалено {total_deleted} дублирующихся записей'
            ))

        # Проверка после очистки
        remaining_duplicates = (
            StoreSelection.objects
            .values('user')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        if remaining_duplicates and not dry_run:
            self.stdout.write(self.style.ERROR(
                f'⚠️ Всё ещё осталось {len(remaining_duplicates)} пользователей с дубликатами!'
            ))
        elif not dry_run:
            self.stdout.write(self.style.SUCCESS('✅ Все дубликаты успешно удалены!'))
