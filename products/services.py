# apps/products/services.py
"""Сервисы для products."""

from decimal import Decimal
from datetime import date
from typing import List, Dict, Any
from django.db import transaction
from django.db.models import Sum, Avg, Q

from .models import (
    Expense,
    Product,
    ProductionBatch,
    ProductImage,
    ProductExpenseRelation
)


class ExpenseService:
    """Сервис расходов."""

    @classmethod
    def get_total_expenses_for_date(cls, date_obj: date) -> Dict[str, Decimal]:
        """
        Получить общие расходы на дату.

        Returns:
            {
                'daily': Decimal,
                'monthly_per_day': Decimal,
                'total': Decimal
            }
        """
        expenses = Expense.objects.filter(is_active=True)

        daily = expenses.aggregate(
            total=Sum('daily_amount')
        )['total'] or Decimal('0')

        monthly = expenses.aggregate(
            total=Sum('monthly_amount')
        )['total'] or Decimal('0')

        monthly_per_day = monthly / Decimal('30')

        return {
            'daily': daily,
            'monthly_per_day': monthly_per_day,
            'total': daily + monthly_per_day
        }

    @classmethod
    def get_expenses_summary(cls) -> Dict[str, Any]:
        """Сводка по расходам."""
        from django.db.models import Count

        expenses_data = cls.get_total_expenses_for_date(date.today())

        counts = Expense.objects.filter(is_active=True).aggregate(
            total=Count('id'),
            physical=Count('id', filter=Q(expense_type='physical')),
            overhead=Count('id', filter=Q(expense_type='overhead'))
        )

        return {
            'total_daily': expenses_data['daily'],
            'total_monthly': expenses_data['daily'] * Decimal('30'),
            'monthly_per_day': expenses_data['monthly_per_day'],
            'total_per_day': expenses_data['total'],
            'expenses_count': counts['total'],
            'physical_count': counts['physical'],
            'overhead_count': counts['overhead']
        }


class ProductionService:
    """Сервис производства."""

    @classmethod
    @transaction.atomic
    def create_production_batch(
            cls,
            product_id: int,
            date_obj: date,
            quantity_produced: Decimal,
            notes: str = ''
    ) -> ProductionBatch:
        """
        Создать производственную запись.

        Args:
            product_id: ID товара
            date_obj: Дата производства
            quantity_produced: Произведено единиц
            notes: Заметки
        """
        product = Product.objects.get(pk=product_id)

        # Получаем расходы
        expenses = ExpenseService.get_total_expenses_for_date(date_obj)

        # Создаём запись
        batch = ProductionBatch.objects.create(
            product=product,
            date=date_obj,
            quantity_produced=quantity_produced,
            total_daily_expenses=expenses['daily'],
            total_monthly_expenses_per_day=expenses['monthly_per_day'],
            notes=notes
        )

        return batch

    @classmethod
    def get_production_history(
            cls,
            product_id: int = None,
            limit: int = 30
    ) -> List[ProductionBatch]:
        """Получить историю производства."""
        queryset = ProductionBatch.objects.all()

        if product_id:
            queryset = queryset.filter(product_id=product_id)

        return queryset.order_by('-date')[:limit]

    @classmethod
    def get_production_stats(cls, product_id: int) -> Dict[str, Any]:
        """Статистика производства товара."""
        from django.db.models import Min, Max, Count

        stats = ProductionBatch.objects.filter(
            product_id=product_id
        ).aggregate(
            avg_cost=Avg('cost_price_calculated'),
            min_cost=Min('cost_price_calculated'),
            max_cost=Max('cost_price_calculated'),
            total_qty=Sum('quantity_produced'),
            count=Count('id')
        )

        return {
            'avg_cost_price': stats['avg_cost'] or Decimal('0'),
            'min_cost_price': stats['min_cost'] or Decimal('0'),
            'max_cost_price': stats['max_cost'] or Decimal('0'),
            'total_produced': stats['total_qty'] or Decimal('0'),
            'batches_count': stats['count'] or 0
        }


class ProductService:
    """Сервис товаров."""

    @classmethod
    def get_catalog_for_stores(cls) -> List[Dict[str, Any]]:
        """
        Каталог для магазинов.

        Магазины видят только final_price!
        """
        products = Product.objects.filter(
            is_active=True,
            is_available=True
        ).prefetch_related('images')

        catalog = []
        for product in products:
            main_image = product.images.filter(order=0).first()

            catalog.append({
                'id': product.id,
                'name': product.name,
                'description': product.description,
                'unit': product.unit,
                'is_weight_based': product.is_weight_based,
                'is_bonus': product.is_bonus,
                'final_price': float(product.final_price),
                'price_per_100g': float(product.price_per_100g) if product.is_weight_based else None,
                'stock_quantity': float(product.stock_quantity),
                'main_image': main_image.image.url if main_image else None,
                'images_count': product.images.count()
            })

        return catalog

    @classmethod
    def get_product_details(cls, product_id: int, for_admin: bool = False) -> Dict[str, Any]:
        """
        Детали товара.

        Args:
            product_id: ID товара
            for_admin: True - показать все данные, False - только для просмотра
        """
        product = Product.objects.get(pk=product_id)

        data = {
            'id': product.id,
            'name': product.name,
            'description': product.description,
            'unit': product.unit,
            'is_weight_based': product.is_weight_based,
            'is_bonus': product.is_bonus,
            'final_price': float(product.final_price),
            'stock_quantity': float(product.stock_quantity),
            'is_active': product.is_active,
            'is_available': product.is_available,
        }

        if for_admin:
            # Для админа - полная информация
            prod_stats = ProductionService.get_production_stats(product_id)

            data.update({
                'average_cost_price': float(product.average_cost_price),
                'markup_percentage': float(product.markup_percentage),
                'profit_per_unit': float(product.profit_per_unit),
                'popularity_weight': float(product.popularity_weight),
                'production_stats': prod_stats,
            })

        # Изображения
        data['images'] = [
            {
                'id': img.id,
                'url': img.image.url,
                'order': img.order
            }
            for img in product.images.all()
        ]

        return data

    @classmethod
    @transaction.atomic
    def update_markup(
            cls,
            product_id: int,
            markup_percentage: Decimal
    ) -> Product:
        """Обновить наценку товара."""
        product = Product.objects.get(pk=product_id)
        product.markup_percentage = markup_percentage
        product.save()  # Автоматически пересчитает final_price
        return product


class ProductImageService:
    """Сервис изображений."""

    @classmethod
    @transaction.atomic
    def add_images(
            cls,
            product_id: int,
            images: List[Any]
    ) -> List[ProductImage]:
        """Добавить изображения (до 3 штук)."""
        product = Product.objects.get(pk=product_id)
        existing = product.images.count()

        if existing + len(images) > 3:
            raise ValueError(
                f'Максимум 3 изображения. Сейчас: {existing}'
            )

        created = []
        for i, image_file in enumerate(images):
            img = ProductImage.objects.create(
                product=product,
                image=image_file,
                order=existing + i
            )
            created.append(img)

        return created

    @classmethod
    @transaction.atomic
    def delete_image(cls, image_id: int) -> None:
        """Удалить изображение и переупорядочить."""
        from django.db.models import F

        image = ProductImage.objects.get(pk=image_id)
        deleted_order = image.order
        product_id = image.product_id

        image.delete()

        # Переупорядочить
        ProductImage.objects.filter(
            product_id=product_id,
            order__gt=deleted_order
        ).update(order=F('order') - 1)

    @classmethod
    @transaction.atomic
    def reorder_images(
            cls,
            product_id: int,
            new_order: List[int]
    ) -> None:
        """Изменить порядок изображений."""
        for i, image_id in enumerate(new_order):
            ProductImage.objects.filter(
                id=image_id,
                product_id=product_id
            ).update(order=i)