# apps/products/finance.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

import calendar
from django.db.models import Sum

from .models import (
    ProductionRecord,
    ProductionItem,
    Expense,
    MechanicalExpenseEntry,
)
from .services import CostCalculator  # уже есть в products.services


@dataclass
class DailyFinanceResult:
    """
    Агрегированный фин. результат по одному ProductionRecord
    (один день / одна производственная смена).
    """

    record_id: int
    date: date

    total_quantity: Decimal
    ingredient_cost: Decimal
    overhead_cost: Decimal
    total_cost: Decimal
    revenue: Decimal
    net_profit: Decimal

    fixed_daily_overhead: Decimal
    mechanical_daily_overhead: Decimal

    def as_dict(self) -> Dict[str, Any]:
        qty = self.total_quantity or Decimal("0")

        if qty > 0:
            cost_per_unit = (self.total_cost / qty).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            profit_per_unit = (self.net_profit / qty).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        else:
            cost_per_unit = Decimal("0")
            profit_per_unit = Decimal("0")

        return {
            "record_id": self.record_id,
            "date": self.date,
            "total_quantity": self.total_quantity,
            "ingredient_cost": self.ingredient_cost,
            "overhead_cost": self.overhead_cost,
            "total_cost": self.total_cost,
            "revenue": self.revenue,
            "net_profit": self.net_profit,
            "fixed_daily_overhead": self.fixed_daily_overhead,
            "mechanical_daily_overhead": self.mechanical_daily_overhead,
            "cost_per_unit": cost_per_unit,
            "profit_per_unit": profit_per_unit,
        }


class ProductionFinanceService:
    """
    Сервис для фин.аналитики производства.

    Основан на уже существующем CostCalculator:

    - берём ProductionRecord + его ProductionItem;
    - прогоняем через CostCalculator.calculate_production_item;
    - агрегируем себестоимость, накладные, выручку, чистую прибыль;
    - отдельно считаем:
        * фикс. накладные (Expense.monthly_amount / days_in_month),
        * переменные накладные (MechanicalExpenseEntry.amount_spent).

    Плюс утилита calculate_scenario — чистая математика под пример заказчика.
    """

    # ---------- Агрегация по ProductionRecord ----------

    @classmethod
    def calculate_for_record(
        cls,
        record: ProductionRecord,
        *,
        recalc_items: bool = True,
        days_in_month: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Полный фин.расчёт по одному ProductionRecord (дню производства).

        Возвращает dict, готовый к сериализации.
        """

        # 1) Пересчитываем каждую позицию производства
        if recalc_items:
            for item in record.items.select_related("product"):
                CostCalculator.calculate_production_item(item)

        items = list(
            record.items.all()
        )  # уже должны быть с заполненными полями себестоимости

        total_quantity = Decimal("0")
        ingredient_cost = Decimal("0")
        overhead_cost = Decimal("0")
        total_cost = Decimal("0")
        revenue = Decimal("0")
        net_profit = Decimal("0")

        for item in items:
            qty = getattr(item, "quantity_produced", None) or Decimal("0")

            total_quantity += qty
            ingredient_cost += getattr(item, "ingredient_cost", Decimal("0"))
            overhead_cost += getattr(item, "overhead_cost", Decimal("0"))
            total_cost += getattr(item, "total_cost", Decimal("0"))
            revenue += getattr(item, "revenue", Decimal("0"))
            net_profit += getattr(item, "net_profit", Decimal("0"))

        # 2) Накладные: фиксированные (месячные) + механические (дневные)
        if days_in_month is None:
            days_in_month = calendar.monthrange(record.date.year, record.date.month)[1]

        days = Decimal(str(days_in_month))

        overhead_qs = Expense.objects.filter(expense_type="overhead", is_active=True)

        fixed_daily_overhead = Decimal("0")
        for exp in overhead_qs:
            # НЕ механические — считаем из monthly_amount / days_in_month
            if getattr(exp, "state", None) != "mechanical" and getattr(
                exp, "monthly_amount", None
            ):
                fixed_daily_overhead += (
                    Decimal(exp.monthly_amount) / days  # type: ignore[arg-type]
                )

        mechanical_daily_overhead = (
            MechanicalExpenseEntry.objects.filter(record=record).aggregate(
                total=Sum("amount_spent")
            )["total"]
            or Decimal("0")
        )

        result = DailyFinanceResult(
            record_id=record.id,
            date=record.date,
            total_quantity=total_quantity,
            ingredient_cost=ingredient_cost,
            overhead_cost=overhead_cost,
            total_cost=total_cost,
            revenue=revenue,
            net_profit=net_profit,
            fixed_daily_overhead=fixed_daily_overhead,
            mechanical_daily_overhead=mechanical_daily_overhead,
        )

        return result.as_dict()

    # ---------- Чистая математика под примеры заказчика ----------

    @staticmethod
    def calculate_scenario(
        *,
        monthly_overhead: Decimal,
        daily_variable: Decimal,
        daily_output_qty: int,
        price_per_unit: Decimal,
        days_in_month: int = 30,
    ) -> Dict[str, Decimal]:
        """
        Универсальный расчёт “как у заказчика”:

        - monthly_overhead — все месячные расходы (аренда, свет, налоги, з/п и т.д.)
        - daily_variable — все дневные расходы (мука, фарш, доставка, солярка и т.п.)
        - daily_output_qty — сколько пачек/шт в день производится
        - price_per_unit — цена продажи за 1 пачку / 1 шт
        - days_in_month — кол-во дней для деления месячных (по умолчанию 30)

        Возвращает:
        - daily_fixed_overhead
        - daily_variable_expenses
        - daily_total_cost
        - daily_revenue
        - daily_net_profit
        - cost_per_unit
        - profit_per_unit
        """

        if days_in_month <= 0:
            raise ValueError("days_in_month must be > 0")

        q = Decimal(str(daily_output_qty))
        monthly_overhead = Decimal(str(monthly_overhead))
        daily_variable = Decimal(str(daily_variable))
        price_per_unit = Decimal(str(price_per_unit))
        days = Decimal(str(days_in_month))

        # 1) Месячные → дневные
        daily_fixed = (monthly_overhead / days).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # 2) Общие дневные расходы
        daily_total_cost = (daily_fixed + daily_variable).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # 3) Выручка за день
        daily_revenue = (q * price_per_unit).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # 4) Чистая прибыль за день
        daily_net_profit = (daily_revenue - daily_total_cost).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # 5) Себестоимость и прибыль с 1 шт
        if q > 0:
            cost_per_unit = (daily_total_cost / q).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            profit_per_unit = (daily_net_profit / q).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        else:
            cost_per_unit = Decimal("0")
            profit_per_unit = Decimal("0")

        return {
            "monthly_overhead": monthly_overhead,
            "days_in_month": Decimal(days_in_month),
            "daily_fixed_overhead": daily_fixed,
            "daily_variable_expenses": daily_variable,
            "daily_total_cost": daily_total_cost,
            "daily_output_qty": q,
            "price_per_unit": price_per_unit,
            "daily_revenue": daily_revenue,
            "daily_net_profit": daily_net_profit,
            "cost_per_unit": cost_per_unit,
            "profit_per_unit": profit_per_unit,
        }
