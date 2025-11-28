# apps/reports/models.py

from django.conf import settings
from django.db import models


class ReportType(models.TextChoices):
    """Типы отчётов по ТЗ проекта."""
    SALES = "sales", "Продажи"
    DEBTS = "debts", "Долги"
    COSTS = "costs", "Расходы"
    BONUSES = "bonuses", "Бонусы"
    DEFECTS = "defects", "Брак"
    BALANCE = "balance", "Баланс"
    ORDERS = "orders", "Заказы"
    PRODUCTS = "products", "Товары"
    MARKUP = "markup", "Наценка"


class Report(models.Model):
    """
    Универсальная модель отчёта.

    data:
        {
          "summary": { ... агрегаты ... },
          "items": [ ... строки ... ],
          "diagram": {
              "labels": [...],
              "values": [...]
          }
        }
    """

    type = models.CharField(
        max_length=32,
        choices=ReportType.choices,
        verbose_name="Тип отчёта",
    )
    date_from = models.DateField(verbose_name="Период с")
    date_to = models.DateField(verbose_name="Период по")
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="Кем сгенерирован",
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Данные отчёта",
    )
    pdf_file = models.FileField(
        upload_to="reports/",
        null=True,
        blank=True,
        verbose_name="PDF файл",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        db_table = "reports"
        ordering = ["-created_at"]
        verbose_name = "Отчёт"
        verbose_name_plural = "Отчёты"
        indexes = [
            models.Index(fields=["type", "date_from", "date_to"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()} ({self.date_from}–{self.date_to})"

    @property
    def diagram(self) -> dict:
        """
        Безопасно вернуть данные для диаграммы.

        Всегда:
        {
          "labels": [...],
          "values": [...]
        }
        """
        if not isinstance(self.data, dict):
            return {"labels": [], "values": []}
        diagram = self.data.get("diagram") or {}
        return {
            "labels": diagram.get("labels", []) or [],
            "values": diagram.get("values", []) or [],
        }
