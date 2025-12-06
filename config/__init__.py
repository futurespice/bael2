# config/__init__.py
"""
Инициализация проекта Django.

Загружаем Celery при старте Django, чтобы shared_task декоратор
использовал правильное приложение.
"""

from .celery import app as celery_app

__all__ = ('celery_app',)
