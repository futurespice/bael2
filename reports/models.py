# apps/reports/models.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Модели для статистики и отчётов согласно ТЗ v2.0.

ОСНОВНАЯ МОДЕЛЬ:
- DailyReport: Кеширование агрегированных данных

ТЗ v2.0 СТАТИСТИКА:
- Круговые диаграммы (доход, долг, погашенный долг, бонусы, брак, расходы)
- Календарная фильтрация (день, неделя, месяц, полгода, год, за всё время)
- Фильтрация по магазинам, городам, областям

ПОЛЯ СТАТИСТИКИ:
- Доход (реальный): сумма от продаж + погашенных долгов
- Брак: сумма убытка, идёт в минус
- Бонусы: считаются по количеству, не влияют на сумму
- Расходы: ручной ввод от партнёров (только у админа)
- Долги (непогашенные): показатель неуплаченных товаров
- Погашенные долги: идут в доход
- Общий баланс: доход - брак - расходы - долг
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class DailyReport(models.Model):
    """
    Ежедневная статистика (кеш для быстрого доступа).

    ТЗ v2.0: "Круговые диаграммы для визуализации статистики"

    Кешируется ежедневно через Celery task для:
    - Быстрого построения диаграмм
    - Исторических данных
    - Фильтрации по периодам
    """

    # === Фильтры ===
    date = models.DateField(
        verbose_name='Дата',
        db_index=True,
        help_text='Дата отчёта'
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='daily_reports',
        verbose_name='Магазин',
        help_text='Null = общая статистика'
    )

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='daily_reports',
        limit_choices_to={'role': 'partner'},
        verbose_name='Партнёр',
        help_text='Null = общая статистика'
    )

    region = models.ForeignKey(
        'stores.Region',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='daily_reports',
        verbose_name='Область'
    )

    city = models.ForeignKey(
        'stores.City',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='daily_reports',
        verbose_name='Город'
    )

    # === ФИНАНСОВЫЕ ПОКАЗАТЕЛИ ===

    # Доход (реальный)
    income = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Доход',
        help_text='Сумма от продаж + погашенных долгов'
    )

    # Долги
    debt = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Непогашенный долг',
        help_text='Показатель неуплаченных товаров'
    )

    # Погашенные долги (идут в доход, но показываются отдельно)
    paid_debt = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Погашенные долги',
        help_text='Не в диаграмме, только в поле'
    )

    # Бонусы (по количеству)
    bonus_count = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Бонусы (штук)',
        help_text='Считаются по количеству, не влияют на сумму'
    )

    # Брак (убыток)
    defect_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Брак',
        help_text='Сумма убытка, идёт в минус'
    )

    # Расходы партнёров (только у админа)
    expenses = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Расходы',
        help_text='Ручной ввод от партнёров'
    )

    # === КОЛИЧЕСТВЕННЫЕ ПОКАЗАТЕЛИ ===

    orders_count = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Количество заказов'
    )

    products_sold_count = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Количество проданных товаров'
    )

    # === СИСТЕМНЫЕ ПОЛЯ ===

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Создано'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Обновлено'
    )

    class Meta:
        db_table = 'daily_reports'
        verbose_name = 'Ежедневный отчёт'
        verbose_name_plural = 'Ежедневные отчёты'
        ordering = ['-date']
        unique_together = [
            ['date', 'store', 'partner', 'region', 'city']
        ]
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['store', 'date']),
            models.Index(fields=['partner', 'date']),
            models.Index(fields=['region', 'date']),
            models.Index(fields=['city', 'date']),
        ]

    def __str__(self) -> str:
        scope = []
        if self.store:
            scope.append(f"Магазин: {self.store.name}")
        if self.partner:
            scope.append(f"Партнёр: {self.partner.get_full_name()}")
        if self.region:
            scope.append(f"Область: {self.region.name}")
        if self.city:
            scope.append(f"Город: {self.city.name}")

        scope_str = ", ".join(scope) if scope else "Общая"
        return f"Отчёт {self.date} ({scope_str})"

    # === ВЫЧИСЛЯЕМЫЕ ПОЛЯ ===

    @property
    def total_balance(self) -> Decimal:
        """
        Общий баланс: доход - брак - расходы - долг.

        ТЗ: "При нуле или минусе — выводить отрицательную прибыль"
        """
        return (
                self.income
                - self.defect_amount
                - self.expenses
                - self.debt
        )

    @property
    def profit(self) -> Decimal:
        """Прибыль (без учёта долга)."""
        return self.income - self.defect_amount - self.expenses

    def get_chart_data(self) -> Dict[str, Decimal]:
        """
        Данные для круговой диаграммы.

        Returns:
            Dict с ключами: income, debt, defect, expenses
        """
        return {
            'income': self.income,
            'debt': self.debt,
            'defect': self.defect_amount,
            'expenses': self.expenses,
        }