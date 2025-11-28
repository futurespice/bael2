# apps/products/filters.py
"""
Django Filter фильтры для модуля products.
"""

import django_filters
from django.db.models import Q
from decimal import Decimal

from .models import (
    Product,
    Expense,
    Recipe,
    DefectiveProduct,
    ProductionRecord,
    ExpenseType,
    AccountingMode,
    ExpenseStatus,
    DefectStatus,
)


class ExpenseFilter(django_filters.FilterSet):
    """Фильтры для расходов."""

    # По типу
    expense_type = django_filters.ChoiceFilter(choices=ExpenseType.choices)
    accounting_mode = django_filters.ChoiceFilter(choices=AccountingMode.choices)
    status = django_filters.ChoiceFilter(choices=ExpenseStatus.choices)

    # По активности
    is_active = django_filters.BooleanFilter()

    # Поиск
    search = django_filters.CharFilter(method='filter_search')

    # По цене
    price_min = django_filters.NumberFilter(
        field_name='price_per_unit',
        lookup_expr='gte'
    )
    price_max = django_filters.NumberFilter(
        field_name='price_per_unit',
        lookup_expr='lte'
    )

    class Meta:
        model = Expense
        fields = ['expense_type', 'accounting_mode', 'status', 'is_active']

    def filter_search(self, queryset, name, value):
        """Поиск по названию."""
        if not value:
            return queryset
        return queryset.filter(name__icontains=value)


class ProductFilter(django_filters.FilterSet):
    """Фильтры для товаров."""

    # Ценовые фильтры (по итоговой цене)
    price_min = django_filters.NumberFilter(
        field_name='final_price',
        lookup_expr='gte'
    )
    price_max = django_filters.NumberFilter(
        field_name='final_price',
        lookup_expr='lte'
    )

    # По себестоимости
    cost_min = django_filters.NumberFilter(
        field_name='cost_price',
        lookup_expr='gte'
    )
    cost_max = django_filters.NumberFilter(
        field_name='cost_price',
        lookup_expr='lte'
    )

    # Остатки
    in_stock = django_filters.BooleanFilter(method='filter_in_stock')
    low_stock = django_filters.BooleanFilter(method='filter_low_stock')
    stock_min = django_filters.NumberFilter(
        field_name='stock_quantity',
        lookup_expr='gte'
    )
    stock_max = django_filters.NumberFilter(
        field_name='stock_quantity',
        lookup_expr='lte'
    )

    # Тип товара
    is_weight_based = django_filters.BooleanFilter()
    unit = django_filters.CharFilter()

    # Статусы
    is_active = django_filters.BooleanFilter()
    is_available = django_filters.BooleanFilter()

    # Поиск
    search = django_filters.CharFilter(method='filter_search')

    # По наличию рецептов
    has_recipes = django_filters.BooleanFilter(method='filter_has_recipes')

    class Meta:
        model = Product
        fields = [
            'is_active',
            'is_available',
            'is_weight_based',
            'unit',
        ]

    def filter_in_stock(self, queryset, name, value):
        """Фильтр товаров в наличии."""
        if value is True:
            return queryset.filter(stock_quantity__gt=0)
        elif value is False:
            return queryset.filter(stock_quantity=0)
        return queryset

    def filter_low_stock(self, queryset, name, value):
        """Фильтр товаров с низким остатком (< 10)."""
        threshold = Decimal('10')

        if value is True:
            return queryset.filter(
                stock_quantity__gt=0,
                stock_quantity__lt=threshold
            )
        elif value is False:
            return queryset.filter(
                Q(stock_quantity=0) | Q(stock_quantity__gte=threshold)
            )
        return queryset

    def filter_search(self, queryset, name, value):
        """Поиск по названию и описанию."""
        if not value:
            return queryset

        return queryset.filter(
            Q(name__icontains=value) |
            Q(description__icontains=value)
        )

    def filter_has_recipes(self, queryset, name, value):
        """Фильтр по наличию рецептов."""
        if value is True:
            return queryset.filter(recipes__isnull=False).distinct()
        elif value is False:
            return queryset.filter(recipes__isnull=True)
        return queryset


class RecipeFilter(django_filters.FilterSet):
    """Фильтры для рецептов."""

    # По товару
    product = django_filters.NumberFilter(field_name='product_id')
    product_name = django_filters.CharFilter(
        field_name='product__name',
        lookup_expr='icontains'
    )

    # По ингредиенту
    expense = django_filters.NumberFilter(field_name='expense_id')
    expense_name = django_filters.CharFilter(
        field_name='expense__name',
        lookup_expr='icontains'
    )

    class Meta:
        model = Recipe
        fields = ['product', 'expense']


class DefectiveProductFilter(django_filters.FilterSet):
    """Фильтры для бракованных товаров."""

    # По статусу
    status = django_filters.ChoiceFilter(choices=DefectStatus.choices)

    # По дате
    created_after = django_filters.DateFilter(
        field_name='created_at',
        lookup_expr='gte'
    )
    created_before = django_filters.DateFilter(
        field_name='created_at',
        lookup_expr='lte'
    )

    # По товару
    product = django_filters.NumberFilter(field_name='product_id')
    product_name = django_filters.CharFilter(
        field_name='product__name',
        lookup_expr='icontains'
    )

    # По партнёру
    partner = django_filters.NumberFilter(field_name='partner_id')

    class Meta:
        model = DefectiveProduct
        fields = ['status', 'product', 'partner']


class ProductionRecordFilter(django_filters.FilterSet):
    """Фильтры для записей производства."""

    # По дате
    date = django_filters.DateFilter()
    date_from = django_filters.DateFilter(
        field_name='date',
        lookup_expr='gte'
    )
    date_to = django_filters.DateFilter(
        field_name='date',
        lookup_expr='lte'
    )

    # По партнёру
    partner = django_filters.NumberFilter(field_name='partner_id')

    class Meta:
        model = ProductionRecord
        fields = ['date', 'partner']
