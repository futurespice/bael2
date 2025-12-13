from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from decimal import Decimal

from .models import ProductExpenseRelation, Product


@receiver([post_save, post_delete], sender=ProductExpenseRelation)
def recalculate_product_price_on_expense_change(sender, instance, **kwargs):
    """
    Автоматический пересчёт цены товара при изменении связи с расходом.

    Триггер:
    - Добавлена связь ProductExpenseRelation
    - Удалена связь ProductExpenseRelation
    - Изменена пропорция в связи

    Действие:
    - Пересчитать себестоимость товара
    - Применить наценку
    - Обновить final_price
    """
    product = instance.product

    # Пересчитываем себестоимость с учётом всех расходов
    from .services import ProductService

    try:
        # Получаем все связанные расходы
        expense_relations = product.expense_relations.select_related('expense').all()

        if expense_relations.exists():
            # Рассчитываем общую себестоимость
            total_cost = Decimal('0')

            for relation in expense_relations:
                expense = relation.expense
                proportion = relation.proportion or Decimal('1')

                # Расход за единицу * пропорция
                expense_amount = expense.calculate_amount()
                cost_per_unit = expense_amount * proportion
                total_cost += cost_per_unit

            # Обновляем себестоимость
            product.average_cost_price = total_cost.quantize(Decimal('0.01'))

            # Применяем наценку
            markup_multiplier = Decimal('1') + (product.markup_percentage / 100)
            product.final_price = (product.average_cost_price * markup_multiplier).quantize(Decimal('0.01'))

            product.save(update_fields=['average_cost_price', 'final_price'])

            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"✅ Цена обновлена | Товар: {product.name} | "
                f"Себестоимость: {product.average_cost_price} | "
                f"Цена: {product.final_price}"
            )

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка пересчёта цены для {product.name}: {e}")