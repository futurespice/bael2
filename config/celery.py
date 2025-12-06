# config/celery.py
"""
Конфигурация Celery для проекта БайЭл.

Celery используется для:
- Отправки email уведомлений
- Push-уведомлений через FCM
- Пересчёта статистики
- Других фоновых задач
"""

import os
from celery import Celery

# Устанавливаем модуль настроек Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Создаём экземпляр Celery
app = Celery('config')

# Загружаем конфигурацию из настроек Django
# Все настройки Celery должны начинаться с CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически находим задачи в приложениях Django
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Тестовая задача для проверки работы Celery."""
    print(f'Request: {self.request!r}')
