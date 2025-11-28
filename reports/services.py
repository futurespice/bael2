# apps/reports/services.py

import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.core.files.base import ContentFile
from django.db.models import Sum
from django.db.models.functions import Coalesce

from .models import Report, ReportType


@dataclass
class ReportContext:
    """Контекст фильтрации при генерации отчёта."""

    date_from: date
    date_to: date
    city_id: Optional[int] = None
    partner_id: Optional[int] = None
    store_id: Optional[int] = None


def _to_float(value: Any) -> float:
    """Безопасно привести Decimal/None к float для JSON."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class ReportGeneratorService:
    """
    Сервис генерации отчётов.

    Все методы возвращают JSON-совместимый dict:
    {
      "summary": {...},
      "items": [...],
      "diagram": {
          "labels": [...],
          "values": [...]
      }
    }
    """

    @classmethod
    def generate_report(
        cls, report_type: str, ctx: ReportContext
    ) -> Dict[str, Any]:
        if report_type == ReportType.SALES:
            return cls.generate_sales_report(ctx)
        if report_type == ReportType.DEBTS:
            return cls.generate_debts_report(ctx)
        if report_type == ReportType.COSTS:
            return cls.generate_costs_report(ctx)
        if report_type == ReportType.BONUSES:
            return cls.generate_bonuses_report(ctx)
        if report_type == ReportType.DEFECTS:
            return cls.generate_defects_report(ctx)
        if report_type == ReportType.BALANCE:
            return cls.generate_balance_report(ctx)
        if report_type == ReportType.ORDERS:
            return cls.generate_orders_report(ctx)
        if report_type == ReportType.PRODUCTS:
            return cls.generate_products_report(ctx)
        if report_type == ReportType.MARKUP:
            return cls.generate_markup_report(ctx)
        raise ValueError(f"Неизвестный тип отчёта: {report_type}")

    # === SALES =================================================================

    @classmethod
    def generate_sales_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Продажи по заказам магазинов (StoreOrder).

        - суммарные продажи
        - продажи по магазинам (diagram)
        """
        from orders.models import StoreOrder  # локальный импорт, чтобы избежать циклов

        qs = StoreOrder.objects.filter(
            created_at__date__gte=ctx.date_from,
            created_at__date__lte=ctx.date_to,
        ).select_related("store", "store__city", "partner")

        if ctx.store_id:
            qs = qs.filter(store_id=ctx.store_id)
        if ctx.partner_id:
            qs = qs.filter(partner_id=ctx.partner_id)
        if ctx.city_id:
            qs = qs.filter(store__city_id=ctx.city_id)

        agg = qs.aggregate(total_amount=Coalesce(Sum("total_amount"), Decimal("0")))
        total_amount = agg["total_amount"]

        rows = (
            qs.values("store_id", "store__name")
            .annotate(total_amount=Coalesce(Sum("total_amount"), Decimal("0")))
            .order_by("-total_amount")
        )

        items: List[Dict[str, Any]] = [
            {
                "store_id": row["store_id"],
                "store_name": row["store__name"],
                "total_amount": _to_float(row["total_amount"]),
            }
            for row in rows
        ]

        diagram = {
            "labels": [row["store__name"] for row in rows],
            "values": [_to_float(row["total_amount"]) for row in rows],
        }

        return {
            "summary": {
                "total_sales": _to_float(total_amount),
                "orders_count": qs.count(),
            },
            "items": items,
            "diagram": diagram,
        }

    # === DEBTS ================================================================

    @classmethod
    def generate_debts_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Долги магазинов.

        Берём Store.debt и фильтруем по городу/партнёру.
        """
        from stores.models import Store

        qs = Store.objects.all().select_related("city", "region", "partner")

        if ctx.city_id:
            qs = qs.filter(city_id=ctx.city_id)
        if ctx.partner_id:
            qs = qs.filter(partner_id=ctx.partner_id)
        if ctx.store_id:
            qs = qs.filter(id=ctx.store_id)

        agg = qs.aggregate(total_debt=Coalesce(Sum("debt"), Decimal("0")))
        total_debt = agg["total_debt"]

        rows = (
            qs.values("id", "name", "city__name", "partner__name")
            .annotate(debt=Coalesce(Sum("debt"), Decimal("0")))
            .order_by("-debt")
        )

        items = [
            {
                "store_id": row["id"],
                "store_name": row["name"],
                "city_name": row["city__name"],
                "partner_name": row["partner__name"],
                "debt": _to_float(row["debt"]),
            }
            for row in rows
        ]

        diagram = {
            "labels": [row["name"] for row in rows],
            "values": [_to_float(row["debt"]) for row in rows],
        }

        return {
            "summary": {
                "total_debt": _to_float(total_debt),
                "stores_count": qs.count(),
            },
            "items": items,
            "diagram": diagram,
        }

    # === COSTS ================================================================

    @classmethod
    def generate_costs_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Отчёт по расходам (Expense + MechanicalExpenseEntry).
        """
        from products.models import Expense, MechanicalExpenseEntry

        expenses_qs = Expense.objects.filter(
            date__gte=ctx.date_from,
            date__lte=ctx.date_to,
        )

        # Привязанные к производству механические расходы
        mech_qs = MechanicalExpenseEntry.objects.filter(
            record__date__gte=ctx.date_from,
            record__date__lte=ctx.date_to,
        )

        total_expenses = expenses_qs.aggregate(
            total=Coalesce(Sum("amount"), Decimal("0"))
        )["total"]
        total_mech = mech_qs.aggregate(
            total=Coalesce(Sum("amount"), Decimal("0"))
        )["total"]
        total = (total_expenses or Decimal("0")) + (total_mech or Decimal("0"))

        by_type = (
            expenses_qs.values("expense_type")
            .annotate(total=Coalesce(Sum("amount"), Decimal("0")))
            .order_by("-total")
        )

        items = [
            {
                "expense_type": row["expense_type"],
                "total_amount": _to_float(row["total"]),
            }
            for row in by_type
        ]

        diagram = {
            "labels": [row["expense_type"] for row in by_type],
            "values": [_to_float(row["total"]) for row in by_type],
        }

        return {
            "summary": {
                "total_expenses": _to_float(total_expenses),
                "total_mechanical": _to_float(total_mech),
                "total": _to_float(total),
            },
            "items": items,
            "diagram": diagram,
        }

    # === BONUSES ==============================================================

    @classmethod
    def generate_bonuses_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Отчёт по бонусам (BonusHistory).
        """
        from products.models import BonusHistory

        qs = BonusHistory.objects.filter(
            created_at__date__gte=ctx.date_from,
            created_at__date__lte=ctx.date_to,
        ).select_related("store", "partner", "product")

        if ctx.store_id:
            qs = qs.filter(store_id=ctx.store_id)
        if ctx.partner_id:
            qs = qs.filter(partner_id=ctx.partner_id)
        if ctx.city_id:
            qs = qs.filter(store__city_id=ctx.city_id)

        agg = qs.aggregate(
            total_bonus_value=Coalesce(Sum("bonus_value"), Decimal("0")),
            total_quantity=Coalesce(Sum("quantity"), 0),
        )

        by_store = (
            qs.values("store_id", "store__name")
            .annotate(total_value=Coalesce(Sum("bonus_value"), Decimal("0")))
            .order_by("-total_value")
        )

        items = [
            {
                "store_id": row["store_id"],
                "store_name": row["store__name"],
                "bonus_value": _to_float(row["total_value"]),
            }
            for row in by_store
        ]

        diagram = {
            "labels": [row["store__name"] for row in by_store],
            "values": [_to_float(row["total_value"]) for row in by_store],
        }

        return {
            "summary": {
                "total_bonus_value": _to_float(agg["total_bonus_value"]),
                "total_bonus_quantity": int(agg["total_quantity"] or 0),
            },
            "items": items,
            "diagram": diagram,
        }

    # === DEFECTS ==============================================================

    @classmethod
    def generate_defects_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Отчёт по браку (DefectiveProduct).
        """
        from products.models import DefectiveProduct

        qs = DefectiveProduct.objects.filter(
            reported_at__date__gte=ctx.date_from,
            reported_at__date__lte=ctx.date_to,
        ).select_related("product", "store", "partner")

        if ctx.store_id:
            qs = qs.filter(store_id=ctx.store_id)
        if ctx.partner_id:
            qs = qs.filter(partner_id=ctx.partner_id)
        if ctx.city_id:
            qs = qs.filter(store__city_id=ctx.city_id)

        agg = qs.aggregate(
            total_quantity=Coalesce(Sum("quantity"), 0),
        )

        by_product = (
            qs.values("product_id", "product__name")
            .annotate(total_quantity=Coalesce(Sum("quantity"), 0))
            .order_by("-total_quantity")
        )

        items = [
            {
                "product_id": row["product_id"],
                "product_name": row["product__name"],
                "quantity": int(row["total_quantity"] or 0),
            }
            for row in by_product
        ]

        diagram = {
            "labels": [row["product__name"] for row in by_product],
            "values": [int(row["total_quantity"] or 0) for row in by_product],
        }

        return {
            "summary": {
                "total_defects": int(agg["total_quantity"] or 0),
                "reports_count": qs.count(),
            },
            "items": items,
            "diagram": diagram,
        }

    # === BALANCE ==============================================================

    @classmethod
    def generate_balance_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Баланс: продажи - расходы - бонусы - брак (приблизительно).
        """
        sales = cls.generate_sales_report(ctx)
        costs = cls.generate_costs_report(ctx)
        bonuses = cls.generate_bonuses_report(ctx)
        defects = cls.generate_defects_report(ctx)

        total_sales = _to_float(sales["summary"]["total_sales"])
        total_costs = _to_float(costs["summary"]["total"])
        total_bonus_value = _to_float(bonuses["summary"]["total_bonus_value"])
        # Брак в деньгах: пока считаем только количеством (денег нет) — 0
        total_defects_value = 0.0

        profit = total_sales - total_costs - total_bonus_value - total_defects_value

        return {
            "summary": {
                "total_sales": total_sales,
                "total_costs": total_costs,
                "total_bonus_value": total_bonus_value,
                "total_defects_value": total_defects_value,
                "profit": profit,
            },
            "items": [],
            "diagram": {
                "labels": ["Продажи", "Расходы", "Бонусы", "Брак", "Прибыль"],
                "values": [
                    total_sales,
                    total_costs,
                    total_bonus_value,
                    total_defects_value,
                    profit,
                ],
            },
        }

    # === ORDERS ==============================================================

    @classmethod
    def generate_orders_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Статистика по заказам (PartnerOrder + StoreOrder).
        """
        from orders.models import PartnerOrder, StoreOrder

        partner_qs = PartnerOrder.objects.filter(
            created_at__date__gte=ctx.date_from,
            created_at__date__lte=ctx.date_to,
        ).select_related("partner")
        store_qs = StoreOrder.objects.filter(
            created_at__date__gte=ctx.date_from,
            created_at__date__lte=ctx.date_to,
        ).select_related("store", "partner")

        if ctx.partner_id:
            partner_qs = partner_qs.filter(partner_id=ctx.partner_id)
            store_qs = store_qs.filter(partner_id=ctx.partner_id)
        if ctx.store_id:
            store_qs = store_qs.filter(store_id=ctx.store_id)
        if ctx.city_id:
            store_qs = store_qs.filter(store__city_id=ctx.city_id)

        partner_total = partner_qs.aggregate(
            total=Coalesce(Sum("total_amount"), Decimal("0"))
        )["total"]
        store_total = store_qs.aggregate(
            total=Coalesce(Sum("total_amount"), Decimal("0"))
        )["total"]

        return {
            "summary": {
                "partner_orders_count": partner_qs.count(),
                "partner_orders_total": _to_float(partner_total),
                "store_orders_count": store_qs.count(),
                "store_orders_total": _to_float(store_total),
            },
            "items": [],
            "diagram": {
                "labels": ["Партнёрские заказы", "Заказы магазинов"],
                "values": [_to_float(partner_total), _to_float(store_total)],
            },
        }

    # === PRODUCTS ============================================================

    @classmethod
    def generate_products_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Отчёт по товарам: сколько произведено и продано по каждому продукту.

        Продажи считаем по StoreOrderItem, производство — по ProductionItem.
        """
        from orders.models import StoreOrderItem
        from products.models import ProductionItem

        prod_qs = ProductionItem.objects.filter(
            record__date__gte=ctx.date_from,
            record__date__lte=ctx.date_to,
        ).select_related("product")

        sold_qs = StoreOrderItem.objects.filter(
            order__created_at__date__gte=ctx.date_from,
            order__created_at__date__lte=ctx.date_to,
        ).select_related("product", "order__store", "order__partner")

        if ctx.store_id:
            sold_qs = sold_qs.filter(order__store_id=ctx.store_id)
        if ctx.partner_id:
            sold_qs = sold_qs.filter(order__partner_id=ctx.partner_id)
        if ctx.city_id:
            sold_qs = sold_qs.filter(order__store__city_id=ctx.city_id)

        produced = (
            prod_qs.values("product_id", "product__name")
            .annotate(total_quantity=Coalesce(Sum("quantity"), 0))
        )
        sold = (
            sold_qs.values("product_id", "product__name")
            .annotate(total_quantity=Coalesce(Sum("quantity"), 0))
        )

        produced_map = {
            row["product_id"]: int(row["total_quantity"] or 0) for row in produced
        }
        sold_map = {row["product_id"]: int(row["total_quantity"] or 0) for row in sold}

        product_ids = set(produced_map.keys()) | set(sold_map.keys())

        items: List[Dict[str, Any]] = []
        labels: List[str] = []
        values: List[float] = []

        # нам нужны имена — берём из sold или produced
        name_map: Dict[int, str] = {}
        for row in produced:
            name_map[row["product_id"]] = row["product__name"]
        for row in sold:
            name_map[row["product_id"]] = row["product__name"]

        for product_id in product_ids:
            name = name_map.get(product_id, f"ID {product_id}")
            produced_qty = produced_map.get(product_id, 0)
            sold_qty = sold_map.get(product_id, 0)
            items.append(
                {
                    "product_id": product_id,
                    "product_name": name,
                    "produced_quantity": produced_qty,
                    "sold_quantity": sold_qty,
                }
            )
            labels.append(name)
            values.append(float(sold_qty))

        return {
            "summary": {
                "products_count": len(product_ids),
                "total_produced": int(sum(produced_map.values())),
                "total_sold": int(sum(sold_map.values())),
            },
            "items": items,
            "diagram": {
                "labels": labels,
                "values": values,
            },
        }

    # === MARKUP ===============================================================

    @classmethod
    def generate_markup_report(cls, ctx: ReportContext) -> Dict[str, Any]:
        """
        Отчёт по наценке: (выручка - себестоимость) / себестоимость.

        Себестоимость берём приблизительно из Product.purchase_price * qty.
        """
        from orders.models import StoreOrderItem
        from products.models import Product

        sold_qs = StoreOrderItem.objects.filter(
            order__created_at__date__gte=ctx.date_from,
            order__created_at__date__lte=ctx.date_to,
        ).select_related("product", "order__store", "order__partner")

        if ctx.store_id:
            sold_qs = sold_qs.filter(order__store_id=ctx.store_id)
        if ctx.partner_id:
            sold_qs = sold_qs.filter(order__partner_id=ctx.partner_id)
        if ctx.city_id:
            sold_qs = sold_qs.filter(order__store__city_id=ctx.city_id)

        # revenue по StoreOrderItem.total, себестоимость — purchase_price * quantity
        from django.db.models import F, ExpressionWrapper, DecimalField

        revenue_expr = Coalesce(Sum("total"), Decimal("0"))
        qs = sold_qs.values("product_id", "product__name").annotate(
            revenue=revenue_expr,
            quantity=Coalesce(Sum("quantity"), 0),
        )

        items: List[Dict[str, Any]] = []
        labels: List[str] = []
        values: List[float] = []

        # cache purchase prices
        products = Product.objects.filter(id__in=[row["product_id"] for row in qs])
        price_map = {p.id: p.purchase_price for p in products}

        for row in qs:
            product_id = row["product_id"]
            name = row["product__name"]
            revenue = row["revenue"] or Decimal("0")
            qty = row["quantity"] or 0
            purchase_price = price_map.get(product_id) or Decimal("0")
            cost = purchase_price * Decimal(qty)
            if cost > 0:
                markup = (revenue - cost) / cost
            else:
                markup = Decimal("0")
            items.append(
                {
                    "product_id": product_id,
                    "product_name": name,
                    "revenue": _to_float(revenue),
                    "cost": _to_float(cost),
                    "markup": _to_float(markup),
                }
            )
            labels.append(name)
            values.append(_to_float(markup))

        avg_markup = (
            sum(item["markup"] for item in items) / len(items) if items else 0.0
        )

        return {
            "summary": {
                "products_count": len(items),
                "average_markup": avg_markup,
            },
            "items": items,
            "diagram": {
                "labels": labels,
                "values": values,
            },
        }

    # === PDF ==================================================================

    @staticmethod
    def export_to_pdf_bytes(report: Report) -> bytes:
        """
        Сгенерировать простой PDF-отчёт (Report -> bytes).

        Используем reportlab. Если его нет — вызывающий код должен установить
        зависимость.
        """
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)

        width, height = A4
        y = height - 40

        title = f"Отчёт: {report.get_type_display()} ({report.date_from}–{report.date_to})"
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, title)
        y -= 30

        c.setFont("Helvetica", 10)
        c.drawString(40, y, f"Сгенерирован: {report.generated_by or 'Система'}")
        y -= 20
        c.drawString(40, y, f"Дата создания: {report.created_at}")
        y -= 30

        summary = (report.data or {}).get("summary") or {}
        if summary:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Сводка")
            y -= 20
            c.setFont("Helvetica", 10)
            for key, value in summary.items():
                if y < 50:
                    c.showPage()
                    y = height - 40
                c.drawString(60, y, f"- {key}: {value}")
                y -= 15
            y -= 20

        items = (report.data or {}).get("items") or []
        if items:
            c.setFont("Helvetica-Bold", 12)
            if y < 60:
                c.showPage()
                y = height - 40
            c.drawString(40, y, "Детализация")
            y -= 20
            c.setFont("Helvetica", 9)

            # Пишем первые N строк, чтобы не раздувать pdf
            for row in items[:100]:
                if y < 40:
                    c.showPage()
                    y = height - 40
                c.drawString(60, y, str(row))
                y -= 12

        c.showPage()
        c.save()
        buffer.seek(0)
        return buffer.read()

    @classmethod
    def attach_pdf(cls, report: Report) -> None:
        """Сгенерировать и прикрепить pdf к объекту Report."""
        pdf_bytes = cls.export_to_pdf_bytes(report)
        filename = f"report_{report.id}.pdf"
        report.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
