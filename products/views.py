# apps/products/views.py - ПОЛНАЯ ВЕРСИЯ v3.0
"""
Views для products (на основе правильной архитектуры).

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v3.0:
1. ExpenseViewSet - управление всеми расходами (физические + накладные)
2. ProductRecipeViewSet - управление рецептами товаров
3. ProductViewSet.calculate_production - расчёт по двум сценариям
4. ProductionBatchViewSet - создание партий от количества/Сюзерена
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import (
    Expense,
    Product,
    ProductRecipe,
    ProductionBatch,
    ProductImage,
    ProductExpenseRelation,
    PartnerExpense,
)
from .serializers import (
    ExpenseSerializer,
    ExpenseCreateSerializer,
    ExpenseListSerializer,
    ProductRecipeSerializer,
    ProductRecipeCreateSerializer,
    ProductListSerializer,
    ProductDetailSerializer,
    ProductCreateSerializer,
    ProductionBatchSerializer,
    ProductionCalculateSerializer,
    ProductionBatchCreateSerializer,
    ProductImageSerializer,
    PartnerExpenseCreateSerializer,
    PartnerExpenseListSerializer,
    ProductExpenseRelationSerializer,
    AccountingDataSaveSerializer,
)
from .permissions import IsAdmin, IsPartner, IsAdminOrPartner
from .services import (
    ProductionCalculator,
    ProductionService,
    OverheadDistributor,
    AccountingService,
)


# =============================================================================
# PAGINATION
# =============================================================================

class StandardPagination(PageNumberPagination):
    """Стандартная пагинация."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# =============================================================================
# EXPENSE VIEWSET
# =============================================================================

class ExpenseViewSet(viewsets.ModelViewSet):
    """
    Управление расходами (физические + накладные).

    API:
    - POST /api/products/expenses/ - создать расход
    - GET /api/products/expenses/ - список расходов
    - GET /api/products/expenses/{id}/ - детали
    - PUT /api/products/expenses/{id}/ - обновить
    - DELETE /api/products/expenses/{id}/ - удалить

    ФИЛЬТРЫ:
    - ?expense_type=physical|overhead
    - ?expense_status=suzerain|vassal|civilian
    - ?is_active=true|false
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = Expense.objects.all().order_by('name')
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ExpenseCreateSerializer
        elif self.action == 'list':
            return ExpenseListSerializer
        return ExpenseSerializer

    def get_queryset(self):
        """Фильтрация."""
        queryset = super().get_queryset()

        # Фильтр по типу
        expense_type = self.request.query_params.get('expense_type')
        if expense_type:
            queryset = queryset.filter(expense_type=expense_type)

        # Фильтр по статусу
        expense_status = self.request.query_params.get('expense_status')
        if expense_status:
            queryset = queryset.filter(expense_status=expense_status)

        # Фильтр по активности
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            is_active_bool = is_active.lower() == 'true'
            queryset = queryset.filter(is_active=is_active_bool)

        return queryset

    def _validate_regular_overhead(self, expense):
        """Validate that expense is overhead with apply_type=regular."""
        if expense.expense_type != 'overhead':
            return Response({
                'error': 'This endpoint works only for overhead expenses',
                'expense_type': expense.expense_type,
                'hint': 'Physical expenses are linked via ProductRecipe',
            }, status=status.HTTP_400_BAD_REQUEST)
        if expense.apply_type != 'regular':
            return Response({
                'error': 'This endpoint works only for regular expenses',
                'apply_type': expense.apply_type,
                'hint': 'Universal expenses are auto-applied to all products',
            }, status=status.HTTP_400_BAD_REQUEST)
        return None

    @extend_schema(
        summary="Products without this expense",
        description=(
            "Returns active products NOT linked to this expense via ProductRecipe.\n"
            "Works ONLY for overhead expenses with apply_type='regular'."
        ),
        parameters=[
            OpenApiParameter(
                name='search',
                type=OpenApiTypes.STR,
                description='Search by product name',
            ),
            OpenApiParameter(
                name='is_active',
                type=OpenApiTypes.BOOL,
                description='Filter by product active status',
            ),
        ],
        responses={
            200: ProductListSerializer(many=True),
            400: {'description': 'Wrong expense type or apply type'},
            404: {'description': 'Expense not found'},
        },
    )
    @action(detail=True, methods=['get'], url_path='products-without')
    def products_without(self, request, pk=None):
        """Get products WITHOUT this expense applied."""
        expense = get_object_or_404(Expense, pk=pk)

        error = self._validate_regular_overhead(expense)
        if error:
            return error

        # Get product IDs that already have this expense
        products_with_expense = ProductRecipe.objects.filter(
            expense=expense,
        ).values_list('product_id', flat=True)

        # Get products WITHOUT this expense
        queryset = Product.objects.exclude(
            id__in=products_with_expense,
        ).filter(is_available=True)

        # is_active filter (defaults to True)
        is_active = request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        else:
            queryset = queryset.filter(is_active=True)

        # Search filter
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)

        queryset = queryset.order_by('name')

        # Pagination
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ProductListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ProductListSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Mechanical expenses for accounting",
        description="Returns all expenses with expense_state=mechanical for the accounting screen.",
        responses={200: {'description': 'List of mechanical expenses'}},
    )
    @action(detail=False, methods=['get'], url_path='mechanical-accounting')
    def mechanical_accounting(self, request):
        """
        GET /api/products/expenses/mechanical-accounting/

        Возвращает ТОЛЬКО накладные расходы с expense_state=mechanical.
        Физические расходы (мука, фарш, лук) здесь НЕ отображаются —
        они управляются через рецепты товаров (ProductRecipe).

        Query params:
        - apply_type: universal | regular (опционально, без фильтра — все)
        """
        queryset = Expense.objects.filter(
            expense_type='overhead',   # ← ТОЛЬКО накладные (BUG FIX)
            expense_state='mechanical',
            is_active=True,
        ).order_by('name')

        # Опциональный фильтр по apply_type
        apply_type_filter = self.request.query_params.get('apply_type')
        if apply_type_filter in ('universal', 'regular'):
            queryset = queryset.filter(apply_type=apply_type_filter)

        data = [
            {
                'id': exp.id,
                'name': exp.name,
                'expense_type': exp.expense_type,
                'expense_status': exp.expense_status,
                'expense_state': exp.expense_state,
                'apply_type': exp.apply_type,
                'monthly_amount': str(exp.monthly_amount),
                'daily_amount': str(exp.daily_amount),
            }
            for exp in queryset
        ]

        return Response({'mechanical_expenses': data})

    @extend_schema(
        summary="Add products to regular overhead expense",
        description=(
            "Links products to this expense by creating ProductRecipe records.\n"
            "Uses get_or_create to prevent duplicates.\n"
            "Works ONLY for overhead expenses with apply_type='regular'."
        ),
        request={'type': 'object', 'properties': {
            'product_ids': {'type': 'array', 'items': {'type': 'integer'}},
        }},
        responses={
            200: {'description': 'Products added successfully'},
            400: {'description': 'Wrong expense type, apply type, or invalid product_ids'},
            404: {'description': 'Expense not found'},
        },
    )
    @action(detail=True, methods=['post'], url_path='add-products')
    def add_products(self, request, pk=None):
        """Add products to this expense via ProductRecipe."""
        expense = get_object_or_404(Expense, pk=pk)

        error = self._validate_regular_overhead(expense)
        if error:
            return error

        product_ids = request.data.get('product_ids', [])
        if not isinstance(product_ids, list) or not product_ids:
            return Response({
                'error': 'product_ids must be a non-empty list of integers',
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate that all product IDs exist
        existing_products = Product.objects.filter(id__in=product_ids)
        existing_ids = set(existing_products.values_list('id', flat=True))
        invalid_ids = [pid for pid in product_ids if pid not in existing_ids]
        if invalid_ids:
            return Response({
                'error': f'Products not found: {invalid_ids}',
            }, status=status.HTTP_400_BAD_REQUEST)

        created_count = 0
        for product in existing_products:
            _, created = ProductRecipe.objects.get_or_create(
                product=product,
                expense=expense,
            )
            if created:
                created_count += 1

        return Response({
            'message': f'Added {created_count} product(s)',
            'created': created_count,
            'skipped': len(product_ids) - created_count,
        })


# =============================================================================
# PRODUCT RECIPE VIEWSET
# =============================================================================

class ProductRecipeViewSet(viewsets.ModelViewSet):
    """
    Управление рецептами товаров.

    API:
    - POST /api/products/product-recipes/ - создать рецепт
    - GET /api/products/product-recipes/ - список
    - GET /api/products/product-recipes/{id}/ - детали
    - PUT /api/products/product-recipes/{id}/ - обновить
    - DELETE /api/products/product-recipes/{id}/ - удалить

    ФИЛЬТРЫ:
    - ?product_id=1
    - ?expense_id=2
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = ProductRecipe.objects.all().select_related('product', 'expense')
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ProductRecipeCreateSerializer
        return ProductRecipeSerializer

    def get_queryset(self):
        """Фильтрация."""
        queryset = super().get_queryset()

        # Фильтр по товару
        product_id = self.request.query_params.get('product_id')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        # Фильтр по расходу
        expense_id = self.request.query_params.get('expense_id')
        if expense_id:
            queryset = queryset.filter(expense_id=expense_id)

        return queryset


# =============================================================================
# PRODUCT VIEWSET
# =============================================================================

class ProductViewSet(viewsets.ModelViewSet):
    """
    Управление товарами.

    API:
    - POST /api/products/products/ - создать товар
    - GET /api/products/products/ - список товаров
    - GET /api/products/products/{id}/ - детали
    - PUT /api/products/products/{id}/ - обновить
    - DELETE /api/products/products/{id}/ - удалить

    НОВЫЕ ЭНДПОИНТЫ v3.0:
    - POST /api/products/products/{id}/calculate-production/ - расчёт производства
    """

    permission_classes = [IsAuthenticated]
    queryset = Product.objects.all().prefetch_related('images', 'recipe_items__expense')
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ProductCreateSerializer
        elif self.action in ['retrieve', 'update', 'partial_update']:
            return ProductDetailSerializer
        return ProductListSerializer

    @method_decorator(cache_page(60 * 15))
    def list(self, request, *args, **kwargs):
        """
        Список товаров (кеш 15 минут).
        """
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        """Фильтрация."""
        queryset = super().get_queryset()

        # Для не-админов показываем только активные
        if self.request.user.role != 'admin':
            queryset = queryset.filter(is_active=True, is_available=True)

        # Фильтры
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            is_active_bool = is_active.lower() == 'true'
            queryset = queryset.filter(is_active=is_active_bool)

        is_bonus = self.request.query_params.get('is_bonus')
        if is_bonus is not None:
            is_bonus_bool = is_bonus.lower() == 'true'
            queryset = queryset.filter(is_bonus=is_bonus_bool)

        # Поиск
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset

    def destroy(self, request, *args, **kwargs):
        """Удаление товара с обработкой PROTECT-зависимостей."""
        instance = self.get_object()
        try:
            instance.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except models.ProtectedError:
            return Response(
                {'error': 'Невозможно удалить товар — он используется в заказах, возвратах или инвентаре.'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdmin])
    def calculate_production(self, request, pk=None):
        """
        Рассчитать производство (два сценария).

        POST /api/products/products/{id}/calculate-production/
        Body: {
            "input_type": "quantity",  // или "suzerain"
            "quantity": 200,           // если input_type=quantity
            "suzerain_quantity": 2.0   // если input_type=suzerain
        }

        Ответ:
        {
            "quantity_produced": 200,
            "physical_expenses": [...],
            "overhead_expenses": [...],
            "total_physical_cost": 5000.00,
            "total_overhead_cost": 1000.00,
            "total_cost": 6000.00,
            "cost_per_unit": 30.00,
            "markup_percentage": 20.00,
            "final_price": 36.00,
            "profit_per_unit": 6.00
        }
        """
        product = self.get_object()

        serializer = ProductionCalculateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        input_type = serializer.validated_data['input_type']

        try:
            if input_type == 'quantity':
                quantity = serializer.validated_data['quantity']
                result = ProductionCalculator.calculate_from_quantity(product, quantity)
            else:
                suzerain_quantity = serializer.validated_data['suzerain_quantity']
                result = ProductionCalculator.calculate_from_suzerain(product, suzerain_quantity)

            # Форматируем ответ
            return Response({
                'quantity_produced': float(result.quantity_produced),
                'physical_expenses': [
                    {
                        'expense_id': item.expense_id,
                        'expense_name': item.expense_name,
                        'quantity': float(item.quantity),
                        'unit_price': float(item.unit_price),
                        'total_cost': float(item.total_cost)
                    }
                    for item in result.physical_expenses
                ],
                'overhead_expenses': [
                    {
                        'expense_name': item.expense_name,
                        'total_cost': float(item.total_cost)
                    }
                    for item in result.overhead_expenses
                ],
                'total_physical_cost': float(result.total_physical_cost),
                'total_overhead_cost': float(result.total_overhead_cost),
                'total_cost': float(result.total_cost),
                'cost_per_unit': float(result.cost_per_unit),
                'markup_percentage': float(result.markup_percentage),
                'final_price': float(result.final_price),
                'profit_per_unit': float(result.profit_per_unit)
            })

        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdmin])
    def set_pricing(self, request, pk=None):
        """
        Установить наценку товара (ТЗ v3.0).

        POST /api/products/products/{id}/set-pricing/
        Body: {"markup_percent": 400}
        ИЛИ:  {"markup_amount": 170.87}

        Ответ:
        {
            "id": 1,
            "name": "Пельмени",
            "average_cost_price": "79.13",
            "markup_percentage": "400.00",
            "final_price": "395.65",
            "profit_per_unit": "316.52"
        }
        """
        from decimal import Decimal

        product = self.get_object()

        markup_percent = request.data.get('markup_percent')
        markup_amount = request.data.get('markup_amount')

        if markup_percent is None and markup_amount is None:
            return Response(
                {'error': 'Укажите markup_percent или markup_amount'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                if markup_percent is not None:
                    # Вариант 1: процент наценки
                    product.markup_percentage = Decimal(str(markup_percent))
                    product.manual_price = None  # Сбрасываем ручную цену
                elif markup_amount is not None:
                    # Вариант 2: сумма наценки
                    markup_amount = Decimal(str(markup_amount))
                    new_price = product.average_cost_price + markup_amount
                    product.manual_price = new_price
                    # Рассчитываем process от себестоимости
                    if product.average_cost_price > 0:
                        product.markup_percentage = (markup_amount / product.average_cost_price * 100).quantize(Decimal('0.01'))

                product.save()

            return Response({
                'id': product.id,
                'name': product.name,
                'average_cost_price': str(product.average_cost_price),
                'markup_percentage': str(product.markup_percentage),
                'final_price': str(product.final_price),
                'profit_per_unit': str(product.final_price - product.average_cost_price)
            })

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated, IsAdmin])
    def pricing_analytics(self, request, pk=None):
        """
        Аналитика ценообразования товара (ТЗ Бахрам акя).

        GET /api/products/products/{id}/pricing_analytics/
        Query params:
        - period_days: период анализа (по умолчанию 11 = 1.5 недели)

        Ответ:
        {
            "product": {...},
            "sales_stats": {
                "quantity_sold": 1000,
                "revenue": 50000,
                "sales_share": 15.5  // доля в общих продажах %
            },
            "cost_analysis": {
                "physical_cost": 30000,
                "overhead_share": 5000,
                "total_cost": 35000,
                "cost_per_unit": 35.00
            },
            "pricing": {
                "current_price": 50.00,
                "recommended_price": 52.50,  // на основе рыночной ситуации
                "profit_per_unit": 15.00,
                "margin_percent": 30.0
            },
            "recommendations": [
                "Товар продаётся хорошо, можно поднять цену на 5%",
                "Себестоимость снизилась на 10% за период"
            ]
        }
        """
        from decimal import Decimal
        from datetime import date, timedelta
        from django.db.models import Sum, Avg, Count
        from orders.models import StoreOrderItem, StoreOrderStatus
        from .services import OverheadDistributor, ProductionCalculator
        from .models import ProductRecipe, ExpenseStatus, ExpenseType

        product = self.get_object()

        # Параметры
        period_days = int(request.query_params.get('period_days', 11))
        today = date.today()
        start_date = today - timedelta(days=period_days)

        # =====================================================================
        # 1. СТАТИСТИКА ПРОДАЖ
        # =====================================================================

        sales_data = StoreOrderItem.objects.filter(
            product=product,
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=today,
            order__status=StoreOrderStatus.ACCEPTED,
            is_bonus=False
        ).aggregate(
            quantity_sold=Sum('quantity'),
            revenue=Sum('total'),
            orders_count=Count('order', distinct=True)
        )

        quantity_sold = sales_data['quantity_sold'] or Decimal('0')
        revenue = sales_data['revenue'] or Decimal('0')
        orders_count = sales_data['orders_count'] or 0

        # Общие продажи для расчёта доли
        total_sales = StoreOrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__status=StoreOrderStatus.ACCEPTED,
            is_bonus=False
        ).aggregate(total=Sum('quantity'))['total'] or Decimal('1')

        sales_share = (quantity_sold / total_sales * 100).quantize(Decimal('0.01'))

        # =====================================================================
        # 2. АНАЛИЗ СЕБЕСТОИМОСТИ
        # =====================================================================

        # Физические расходы
        total_physical = Decimal('0')
        physical_details = []

        suzerain_recipe = ProductRecipe.objects.filter(
            product=product,
            expense__expense_status=ExpenseStatus.SUZERAIN
        ).select_related('expense').first()

        if suzerain_recipe and quantity_sold > 0:
            suzerain_volume = quantity_sold * suzerain_recipe.quantity_per_unit
            suzerain_cost = suzerain_volume * (suzerain_recipe.expense.price_per_unit or Decimal('0'))
            total_physical += suzerain_cost

            physical_details.append({
                'name': suzerain_recipe.expense.name,
                'is_suzerain': True,
                'quantity': float(suzerain_volume),
                'unit_price': float(suzerain_recipe.expense.price_per_unit or 0),
                'total': float(suzerain_cost)
            })

            # Остальные физические
            other_recipes = ProductRecipe.objects.filter(
                product=product,
                expense__expense_type=ExpenseType.PHYSICAL
            ).exclude(
                expense__expense_status=ExpenseStatus.SUZERAIN
            ).select_related('expense')

            for recipe in other_recipes:
                if recipe.proportion:
                    item_volume = suzerain_volume * recipe.proportion
                    item_cost = item_volume * (recipe.expense.price_per_unit or Decimal('0'))
                    total_physical += item_cost

                    physical_details.append({
                        'name': recipe.expense.name,
                        'is_suzerain': False,
                        'proportion': float(recipe.proportion),
                        'quantity': float(item_volume),
                        'unit_price': float(recipe.expense.price_per_unit or 0),
                        'total': float(item_cost)
                    })

        # Накладные расходы
        overhead_breakdown = OverheadDistributor.get_overhead_breakdown_for_product(
            product=product,
            quantity_produced=quantity_sold if quantity_sold > 0 else Decimal('1'),
            period_days=period_days
        )

        overhead_share = sum(item.total_cost for item in overhead_breakdown)
        overhead_share_period = overhead_share * period_days  # За весь период

        overhead_details = [
            {
                'name': item.expense_name,
                'daily_amount': float(item.unit_price),
                'product_share': float(item.total_cost),
                'period_total': float(item.total_cost * period_days)
            }
            for item in overhead_breakdown
        ]

        # Итого
        total_cost = total_physical + overhead_share_period

        if quantity_sold > 0:
            cost_per_unit = (total_cost / quantity_sold).quantize(Decimal('0.01'))
        else:
            cost_per_unit = product.average_cost_price or Decimal('0')

        # =====================================================================
        # 3. АНАЛИЗ ЦЕНЫ И РЕКОМЕНДАЦИИ
        # =====================================================================

        current_price = product.final_price or Decimal('0')
        profit_per_unit = current_price - cost_per_unit

        if cost_per_unit > 0:
            margin_percent = ((current_price - cost_per_unit) / cost_per_unit * 100).quantize(Decimal('0.01'))
        else:
            margin_percent = Decimal('0')

        # Рекомендуемая цена (себестоимость + стандартная наценка 30%)
        recommended_price = (cost_per_unit * Decimal('1.3')).quantize(Decimal('0.01'))

        # Генерация рекомендаций
        recommendations = []

        # Анализ продаж
        if sales_share > 20:
            recommendations.append(
                f'🔥 Товар популярен ({sales_share}% продаж). '
                f'Можно рассмотреть повышение цены на 5-10%.'
            )
        elif sales_share < 5:
            recommendations.append(
                f'📉 Низкие продажи ({sales_share}% от общих). '
                f'Рассмотрите снижение цены для стимуляции спроса.'
            )

        # Анализ маржи
        if margin_percent < 20:
            recommendations.append(
                f'⚠️ Низкая маржа ({margin_percent}%). '
                f'Рекомендуется поднять цену минимум до {recommended_price} сом.'
            )
        elif margin_percent > 50:
            recommendations.append(
                f'✅ Хорошая маржа ({margin_percent}%). '
                f'Цена конкурентоспособна.'
            )

        # Сравнение с рекомендуемой ценой
        if current_price < recommended_price * Decimal('0.9'):
            recommendations.append(
                f'💡 Текущая цена ({current_price}) ниже рекомендуемой ({recommended_price}). '
                f'Есть потенциал для роста.'
            )
        elif current_price > recommended_price * Decimal('1.2'):
            recommendations.append(
                f'📊 Текущая цена ({current_price}) выше рекомендуемой ({recommended_price}). '
                f'Следите за объёмом продаж.'
            )

        # =====================================================================
        # 4. ФОРМИРУЕМ ОТВЕТ
        # =====================================================================

        return Response({
            'product': {
                'id': product.id,
                'name': product.name,
                'unit': product.unit,
                'is_weight_based': product.is_weight_based,
            },
            'period': {
                'days': period_days,
                'start_date': str(start_date),
                'end_date': str(today),
            },
            'sales_stats': {
                'quantity_sold': float(quantity_sold),
                'revenue': float(revenue),
                'orders_count': orders_count,
                'sales_share': float(sales_share),
                'avg_quantity_per_day': float((quantity_sold / period_days).quantize(Decimal('0.01'))) if period_days > 0 else 0,
            },
            'cost_analysis': {
                'physical_expenses': physical_details,
                'physical_total': float(total_physical),
                'overhead_expenses': overhead_details,
                'overhead_total': float(overhead_share_period),
                'total_cost': float(total_cost),
                'cost_per_unit': float(cost_per_unit),
            },
            'pricing': {
                'current_price': float(current_price),
                'cost_per_unit': float(cost_per_unit),
                'recommended_price': float(recommended_price),
                'profit_per_unit': float(profit_per_unit),
                'margin_percent': float(margin_percent),
                'markup_percentage': float(product.markup_percentage or 0),
            },
            'recommendations': recommendations,
        })

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated, IsAdmin])
    def cost_dashboard(self, request):
        """
        Сводная таблица себестоимости ВСЕХ товаров (ТЗ Бахрам акя).
        
        GET /api/products/products/cost_dashboard/
        Query params:
        - period_days: период анализа (по умолчанию 11 = 1.5 недели)
        
        Ответ:
        {
            "period_days": 11,
            "date_from": "2026-01-29",
            "date_to": "2026-02-09",
            "total_overhead": "50000.00",
            "products": [
                {
                    "id": 1,
                    "name": "Пельмени зелёные",
                    "quantity_sold": 1000,
                    "revenue": "50000.00",
                    "sales_share": "45.5",
                    "physical_cost": "30000.00",
                    "overhead_share": "22750.00",
                    "total_cost": "52750.00",
                    "cost_per_unit": "52.75",
                    "current_price": "100.00",
                    "profit_per_unit": "47.25",
                    "margin_percent": "47.25"
                }
            ]
        }
        """
        from decimal import Decimal
        from datetime import date, timedelta
        from django.db.models import Sum
        from orders.models import StoreOrderItem, StoreOrderStatus
        from .models import ProductRecipe, ExpenseStatus, ExpenseType, Expense
        
        # Параметры
        period_days = int(request.query_params.get('period_days', 11))
        today = date.today()
        start_date = today - timedelta(days=period_days)
        
        # =====================================================================
        # 1. ПОЛУЧАЕМ ВСЕ НАКЛАДНЫЕ РАСХОДЫ ЗА ПЕРИОД
        # =====================================================================
        total_overhead = Decimal('0')
        overhead_expenses = Expense.objects.filter(
            expense_type=ExpenseType.OVERHEAD,
            is_active=True
        )
        
        for expense in overhead_expenses:
            daily_amount = expense.calculate_amount()
            total_overhead += daily_amount * period_days
        
        # =====================================================================
        # 2. ПОЛУЧАЕМ СТАТИСТИКУ ПРОДАЖ ПО ВСЕМ ТОВАРАМ
        # =====================================================================
        sales_data = StoreOrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=today,
            order__status=StoreOrderStatus.ACCEPTED,
            is_bonus=False
        ).values('product_id', 'product__name').annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum('total')
        )
        
        # Общие продажи для расчёта долей
        total_sales_quantity = sum(
            (item['quantity_sold'] or Decimal('0')) for item in sales_data
        )
        
        # =====================================================================
        # 3. АНАЛИЗИРУЕМ КАЖДЫЙ ТОВАР
        # =====================================================================

        # BUG FIX #3: загружаем ВСЕ рецепты одним bulk-запросом до цикла (N+1 фикс)
        all_product_ids = [item['product_id'] for item in sales_data]
        all_recipes = (
            ProductRecipe.objects
            .filter(product_id__in=all_product_ids)
            .select_related('expense')
        )
        # Индексируем: {product_id: [recipe, ...]}
        recipes_by_product: dict = {}
        for recipe in all_recipes:
            recipes_by_product.setdefault(recipe.product_id, []).append(recipe)

        products_data = []
        
        for item in sales_data:
            product_id = item['product_id']
            product_name = item['product__name']
            quantity_sold = item['quantity_sold'] or Decimal('0')
            revenue = item['revenue'] or Decimal('0')
            
            # Доля в продажах
            if total_sales_quantity > 0:
                sales_share = (quantity_sold / total_sales_quantity * 100).quantize(Decimal('0.01'))
            else:
                sales_share = Decimal('0')
            
            # Накладные для этого товара (пропорционально продажам)
            overhead_share = (total_overhead * sales_share / 100).quantize(Decimal('0.01'))
            
            # Физические расходы (BUG FIX #3: без дополнительных запросов)
            physical_cost = Decimal('0')
            product_recipes = recipes_by_product.get(product_id, [])
            suzerain_recipe = next(
                (r for r in product_recipes
                 if r.expense.expense_status == ExpenseStatus.SUZERAIN),
                None
            )
            
            if suzerain_recipe and quantity_sold > 0:
                suzerain_volume = quantity_sold * suzerain_recipe.quantity_per_unit
                suzerain_cost = suzerain_volume * (suzerain_recipe.expense.price_per_unit or Decimal('0'))
                physical_cost += suzerain_cost

                # Остальные физические (уже загружены выше)
                for recipe in product_recipes:
                    if recipe.expense.expense_status == ExpenseStatus.SUZERAIN:
                        continue
                    if recipe.expense.expense_type != ExpenseType.PHYSICAL:
                        continue
                    if recipe.proportion:
                        item_volume = suzerain_volume * recipe.proportion
                        item_cost = item_volume * (recipe.expense.price_per_unit or Decimal('0'))
                        physical_cost += item_cost
            
            # Общая себестоимость
            total_cost = physical_cost + overhead_share
            
            # Себестоимость за единицу
            if quantity_sold > 0:
                cost_per_unit = (total_cost / quantity_sold).quantize(Decimal('0.01'))
            else:
                cost_per_unit = Decimal('0')
            
            # Текущая цена (из revenue)
            if quantity_sold > 0:
                current_price = (revenue / quantity_sold).quantize(Decimal('0.01'))
            else:
                current_price = Decimal('0')
            
            # Прибыль и маржа
            profit_per_unit = current_price - cost_per_unit
            if current_price > 0:
                margin_percent = (profit_per_unit / current_price * 100).quantize(Decimal('0.01'))
            else:
                margin_percent = Decimal('0')
            
            products_data.append({
                'id': product_id,
                'name': product_name,
                'quantity_sold': float(quantity_sold),
                'revenue': str(revenue),
                'sales_share': str(sales_share),
                'physical_cost': str(physical_cost),
                'overhead_share': str(overhead_share),
                'total_cost': str(total_cost),
                'cost_per_unit': str(cost_per_unit),
                'current_price': str(current_price),
                'profit_per_unit': str(profit_per_unit),
                'margin_percent': str(margin_percent),
            })
        
        # Сортируем по доле продаж (популярные сверху)
        products_data.sort(key=lambda x: float(x['sales_share']), reverse=True)
        
        return Response({
            'period_days': period_days,
            'date_from': start_date.isoformat(),
            'date_to': today.isoformat(),
            'total_overhead': str(total_overhead),
            'total_sales_quantity': float(total_sales_quantity),
            'products_count': len(products_data),
            'products': products_data,
        })


    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated, IsAdmin],
            url_path='accounting-table')
    def accounting_table(self, request):
        """
        GET /api/products/products/accounting-table/
        Таблица учёта данных: по каждому товару себестоимость, расходы, доход.

        Query params:
        - period_days: период в днях (по умолчанию 11)
        - date_from: начало периода YYYY-MM-DD (перекрывает period_days)
        - date_to: конец периода YYYY-MM-DD (по умолчанию сегодня)
        - sort_by: поле сортировки: name (по умолчанию) | date (по дате создания)
        - sort_order: порядок: asc (по умолчанию) | desc
        """
        from decimal import Decimal
        from datetime import date as dt_date, timedelta
        from django.db.models import Sum, Prefetch
        from orders.models import StoreOrderItem, StoreOrderStatus
        from .models import ProductRecipe, ExpenseStatus, ExpenseType as ET, Expense as ExpModel, ApplyType, ProductionBatch

        period_days = int(request.query_params.get('period_days', 11))
        date_to_param = request.query_params.get('date_to')
        date_from_param = request.query_params.get('date_from')
        sort_by = request.query_params.get('sort_by', 'name')
        sort_order = request.query_params.get('sort_order', 'asc')

        today = dt_date.today()
        try:
            end_date = dt_date.fromisoformat(date_to_param) if date_to_param else today
            start_date = dt_date.fromisoformat(date_from_param) if date_from_param else end_date - timedelta(days=period_days)
        except (ValueError, TypeError):
            return Response(
                {'error': 'Неверный формат даты. Используйте YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )

        actual_days = max((end_date - start_date).days, 1)

        # Сортировка на уровне БД (для полей модели)
        db_sort_fields = {'name': 'name', 'date': 'created_at'}
        db_order_field = db_sort_fields.get(sort_by)
        if db_order_field and sort_order == 'desc':
            db_order_field = f'-{db_order_field}'
        elif not db_order_field:
            db_order_field = 'name'

        # =====================================================================
        # 1. Загружаем товары с prefetch рецептов (1 запрос)
        # =====================================================================
        products = list(Product.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'recipe_items',
                queryset=ProductRecipe.objects.select_related('expense').order_by('id'),
            )
        ).order_by(db_order_field))

        # =====================================================================
        # 2. Bulk-запрос продаж по всем товарам (1 запрос)
        # =====================================================================
        all_sales = StoreOrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=end_date,
            order__status=StoreOrderStatus.ACCEPTED,
            is_bonus=False
        ).values('product_id').annotate(
            qty=Sum('quantity'),
            rev=Sum('total')
        )
        sales_by_product = {s['product_id']: s for s in all_sales}

        # =====================================================================
        # 2б. Последняя производственная партия по каждому товару (1 запрос)
        # Используется для расчёта физических расходов и cost_per_unit,
        # когда продаж за период = 0 (например, сразу после save-accounting)
        # =====================================================================
        latest_batches_by_product: dict = {}
        for batch in (
            ProductionBatch.objects.filter(
                date__gte=start_date,
                date__lte=end_date,
            )
            .select_related('product')
            .order_by('product_id', '-date', '-created_at')
        ):
            # Берём только первую (последнюю) для каждого товара
            if batch.product_id not in latest_batches_by_product:
                latest_batches_by_product[batch.product_id] = batch

        # =====================================================================
        # 3. Накладные расходы (1 запрос), разделяем universal vs regular
        # =====================================================================
        overhead_expenses = list(ExpModel.objects.filter(
            expense_type=ET.OVERHEAD,
            is_active=True
        ))
        universal_overhead = [e for e in overhead_expenses if e.apply_type == ApplyType.UNIVERSAL]
        regular_overhead = [e for e in overhead_expenses if e.apply_type == ApplyType.REGULAR]

        # Для regular: загружаем id товаров, привязанных к каждому расходу (1 запрос)
        regular_linked_ids: dict = {}
        if regular_overhead:
            regular_expense_ids = [e.id for e in regular_overhead]
            for rec in ProductRecipe.objects.filter(
                expense_id__in=regular_expense_ids
            ).values('expense_id', 'product_id'):
                regular_linked_ids.setdefault(rec['expense_id'], set()).add(rec['product_id'])

        # =====================================================================
        # 4. Объёмы продаж для распределения накладных
        # =====================================================================
        volume_by_product = {
            pid: (s['qty'] or Decimal('0'))
            for pid, s in sales_by_product.items()
        }
        total_volume_all = sum(volume_by_product.values()) or Decimal('0')
        num_active_products = len(products) or 1

        # Суммарные объёмы привязанных товаров для каждого regular-расхода
        regular_linked_volumes: dict = {}
        for exp in regular_overhead:
            linked = regular_linked_ids.get(exp.id, set())
            total_linked = sum(volume_by_product.get(pid, Decimal('0')) for pid in linked)
            regular_linked_volumes[exp.id] = (total_linked, linked)

        # Маппинг unit_type → человекочитаемая подпись для мобильного клиента
        UNIT_LABELS = {
            'per_piece': 'шт.',
            'per_weight': 'кг.',
            'per_volume': 'л.',
        }

        # =====================================================================
        # 5. Обрабатываем каждый товар (без дополнительных запросов к БД)
        # =====================================================================
        products_result = []
        for product in products:
            sale = sales_by_product.get(product.id, {})
            qty_sold = sale.get('qty') or Decimal('0')
            revenue = sale.get('rev') or Decimal('0')
            product_volume = volume_by_product.get(product.id, Decimal('0'))

            all_recipes = list(product.recipe_items.all())
            suzerain_recipe = next(
                (r for r in all_recipes if r.expense.expense_status == ExpenseStatus.SUZERAIN),
                None
            )

            # --- Определяем базовое количество для расчёта физических расходов ---
            # BUG FIX: раньше физические расходы считались только при qty_sold > 0.
            # Теперь приоритет:
            #   1. Если есть продажи — используем qty_sold (исторические данные)
            #   2. Если есть партия периода — используем batch.quantity_produced
            #   3. Иначе — 0 (расходы не показываем)
            latest_batch = latest_batches_by_product.get(product.id)
            if qty_sold > 0:
                calc_qty = qty_sold          # данные из реальных продаж
                qty_source = 'sales'
            elif latest_batch and latest_batch.quantity_produced > 0:
                calc_qty = latest_batch.quantity_produced  # данные из партии
                qty_source = 'batch'
            else:
                calc_qty = Decimal('0')
                qty_source = 'none'

            # --- Физические расходы ---
            physical_items = []
            total_physical = Decimal('0')
            sz_vol = Decimal('0')

            if suzerain_recipe and calc_qty > 0:
                sz_vol = calc_qty * (suzerain_recipe.quantity_per_unit or Decimal('0'))
                sz_price = suzerain_recipe.expense.price_per_unit or Decimal('0')
                sz_cost = (sz_vol * sz_price).quantize(Decimal('0.01'))
                total_physical += sz_cost
                sz_unit = suzerain_recipe.expense.unit_type or ''
                physical_items.append({
                    'id': suzerain_recipe.expense.id,
                    'name': suzerain_recipe.expense.name,
                    'is_suzerain': True,
                    'quantity': float(sz_vol.quantize(Decimal('0.01'))),
                    'unit_price': float(sz_price),
                    'unit': sz_unit,
                    'unit_label': UNIT_LABELS.get(sz_unit, ''),
                    'total': float(sz_cost),
                })

                for recipe in all_recipes:
                    if recipe.expense.expense_status == ExpenseStatus.SUZERAIN:
                        continue
                    if recipe.expense.expense_type != 'physical':
                        continue
                    unit_price = recipe.expense.price_per_unit or Decimal('0')
                    if recipe.proportion:
                        vol = (sz_vol * recipe.proportion).quantize(Decimal('0.01'))
                        cost = (vol * unit_price).quantize(Decimal('0.01'))
                    elif recipe.quantity_per_unit:
                        vol = (calc_qty * recipe.quantity_per_unit).quantize(Decimal('0.01'))
                        cost = (vol * unit_price).quantize(Decimal('0.01'))
                    else:
                        continue
                    total_physical += cost
                    r_unit = recipe.expense.unit_type or ''
                    physical_items.append({
                        'id': recipe.expense.id,
                        'name': recipe.expense.name,
                        'is_suzerain': False,
                        'quantity': float(vol),
                        'unit_price': float(unit_price),
                        'unit': r_unit,
                        'unit_label': UNIT_LABELS.get(r_unit, ''),
                        'total': float(cost),
                    })

            # --- Рецепты (для UI котлован) ---
            recipe_items_data = [
                {
                    'id': r.id,
                    'expense_id': r.expense.id,
                    'expense_name': r.expense.name,
                    'is_suzerain': r.expense.expense_status == ExpenseStatus.SUZERAIN,
                    'quantity_per_unit': float(r.quantity_per_unit) if r.quantity_per_unit else None,
                    'proportion': float(r.proportion) if r.proportion else None,
                    'absolute_quantity': float(r.absolute_quantity) if r.absolute_quantity else None,
                    'product_quantity': float(r.product_quantity) if r.product_quantity else None,
                    'unit': r.expense.unit_type or '',
                    'unit_price': float(r.expense.price_per_unit or 0),
                }
                for r in all_recipes
                if r.expense.expense_type == 'physical'
            ]

            # --- Накладные расходы ---
            overhead_items = []
            total_overhead = Decimal('0')

            # Universal: распределяем по доле среди ВСЕХ товаров
            for exp in universal_overhead:
                exp_period_total = exp.calculate_amount() * actual_days
                if total_volume_all > 0:
                    share = product_volume / total_volume_all
                else:
                    share = Decimal('1') / num_active_products
                product_share = (exp_period_total * share).quantize(Decimal('0.01'))
                total_overhead += product_share
                overhead_items.append({
                    'id': exp.id,
                    'name': exp.name,
                    'apply_type': 'universal',
                    'total': float(product_share),
                })

            # Regular: только если товар привязан к расходу (галочка)
            for exp in regular_overhead:
                total_linked_vol, linked_ids = regular_linked_volumes[exp.id]
                if product.id not in linked_ids:
                    continue
                exp_period_total = exp.calculate_amount() * actual_days
                if total_linked_vol > 0:
                    share = product_volume / total_linked_vol
                else:
                    share = Decimal('1') / len(linked_ids)
                product_share = (exp_period_total * share).quantize(Decimal('0.01'))
                total_overhead += product_share
                overhead_items.append({
                    'id': exp.id,
                    'name': exp.name,
                    'apply_type': 'regular',
                    'total': float(product_share),
                })

            total_expense = total_physical + total_overhead
            profit = revenue - total_expense

            # BUG FIX: cost_per_unit вычисляем в приоритете:
            # 1. Из batch.cost_per_unit (cost=физ+накл) — если партия есть
            # 2. Текущий период: total_expense / calc_qty
            # 3. product.average_cost_price — запасной вариант
            if latest_batch and latest_batch.cost_per_unit > 0:
                cost_per_unit_val = latest_batch.cost_per_unit
            elif calc_qty > 0 and total_expense > 0:
                cost_per_unit_val = (total_expense / calc_qty).quantize(Decimal('0.01'))
            else:
                cost_per_unit_val = product.average_cost_price

            # income = что получили за период
            # если qty_source='batch' (продаж нет) — income и profit расчётные
            projected_revenue = calc_qty * product.final_price if qty_source == 'batch' else revenue
            projected_profit = projected_revenue - total_expense

            # profit_per_unit: прибыль на единицу (для столбца «Себе-сть» в таблице)
            if calc_qty > 0:
                profit_per_unit_val = (profit / calc_qty).quantize(Decimal('0.01'))
            else:
                profit_per_unit_val = Decimal('0')

            products_result.append({
                'id': product.id,
                'name': product.name,
                'created_at': product.created_at.date().isoformat(),
                'markup_percentage': float(product.markup_percentage),
                'final_price': float(product.final_price),
                'quantity_sold': float(qty_sold),
                'quantity_produced': float(latest_batch.quantity_produced) if latest_batch else None,
                'qty_source': qty_source,  # 'sales' | 'batch' | 'none'
                'input_mode': latest_batch.input_type if latest_batch else 'quantity',
                'cost_per_unit': float(cost_per_unit_val),
                'total_expense': float(total_expense.quantize(Decimal('0.01'))),
                'total_physical_cost': float(total_physical.quantize(Decimal('0.01'))),
                'total_overhead_cost': float(total_overhead.quantize(Decimal('0.01'))),
                'revenue': float(revenue),
                'projected_revenue': float(projected_revenue.quantize(Decimal('0.01'))),
                'profit': float(profit.quantize(Decimal('0.01'))),
                'profit_per_unit': float(profit_per_unit_val),
                'projected_profit': float(projected_profit.quantize(Decimal('0.01'))),
                'physical_expenses': physical_items,
                'overhead_expenses': overhead_items,
                'recipe_items': recipe_items_data,
            })

        # Итого
        grand_expense = sum(p['total_expense'] for p in products_result)
        grand_revenue = sum(p['revenue'] for p in products_result)
        grand_profit = grand_revenue - grand_expense

        return Response({
            'period_days': period_days,
            'date_from': start_date.isoformat(),
            'date_to': end_date.isoformat(),
            'products': products_result,
            'totals': {
                'total_expense': round(grand_expense, 2),
                'total_revenue': round(grand_revenue, 2),
                'net_profit': round(grand_profit, 2),
            }
        })

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated, IsAdmin],
            url_path='save-accounting')
    def save_accounting(self, request):
        """
        POST /api/products/products/save-accounting/
        Сохранить данные учёта (механика + котлован + партии).

        Body:
        {
            "mechanical_expenses": [{"expense_id": 1, "amount": "700"}],
            "recipe_items": [
                {"product_id": 1, "expense_id": 2, "absolute_quantity": "80", "product_quantity": "40"},
                {"product_id": 1, "expense_id": 3, "absolute_quantity": "40"}
            ],
            "production_batches": [{"product_id": 1, "input_type": "quantity", "quantity": "200"}]
        }

        Response:
        {
            "mechanical_updated": 2,
            "recipes_saved": 3,
            "batches_created": 1,
            "updated_products": [
                {
                    "id": 1,
                    "name": "...",
                    "cost_per_unit": 79.13,
                    "markup_percentage": 20.0,
                    "final_price": 95.0,
                    "total_physical_cost": 3000.0,
                    "total_overhead_cost": 1500.0,
                    "total_cost": 4500.0,
                    "quantity_produced": 57
                }
            ]
        }
        """
        serializer = AccountingDataSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            save_results = AccountingService.save_accounting_data(
                mechanical_expenses_data=serializer.validated_data.get('mechanical_expenses', []),
                recipe_items_data=serializer.validated_data.get('recipe_items', []),
                production_batches_data=serializer.validated_data.get('production_batches', [])
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        # BUG FIX: возвращаем пересчитанные данные по затронутым товарам
        # чтобы мобильный клиент не делал дополнительный запрос
        from .models import ProductionBatch
        updated_products = []
        affected_product_ids = set()

        for item in serializer.validated_data.get('production_batches', []):
            affected_product_ids.add(item['product_id'])
        for item in serializer.validated_data.get('recipe_items', []):
            affected_product_ids.add(item['product_id'])

        if affected_product_ids:
            from datetime import date as _dt
            today = _dt.today()
            latest_batches = (
                ProductionBatch.objects
                .filter(product_id__in=affected_product_ids)
                .select_related('product')
                .order_by('product_id', '-date', '-created_at')
            )
            seen = set()
            for batch in latest_batches:
                if batch.product_id in seen:
                    continue
                seen.add(batch.product_id)
                # BUG FIX #4: refresh_from_db чтобы получить актуальные значения после update_average_cost_price
                batch.product.refresh_from_db()
                updated_products.append({
                    'id': batch.product_id,
                    'name': batch.product.name,
                    'final_price': float(batch.product.final_price),
                    'average_cost_price': float(batch.product.average_cost_price),
                    'markup_percentage': float(batch.product.markup_percentage),
                    'cost_per_unit': float(batch.cost_per_unit),
                    'total_physical_cost': float(batch.total_physical_cost),
                    'total_overhead_cost': float(batch.total_overhead_cost),
                    'total_cost': float(batch.total_physical_cost + batch.total_overhead_cost),
                    'quantity_produced': float(batch.quantity_produced),
                    'batch_date': str(batch.date),
                })

        return Response({
            **save_results,
            'updated_products': updated_products,
        })


# =============================================================================
# PRODUCTION BATCH VIEWSET
# =============================================================================

class ProductionBatchViewSet(viewsets.ModelViewSet):
    """
    Производственные партии.

    API:
    - POST /api/products/production-batches/ - создать партию
    - GET /api/products/production-batches/ - список партий
    - GET /api/products/production-batches/{id}/ - детали

    ФИЛЬТРЫ:
    - ?product_id=1
    - ?date_from=2026-01-01
    - ?date_to=2026-01-31
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = ProductionBatch.objects.all().select_related('product').order_by('-date', '-created_at')
    serializer_class = ProductionBatchSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        """Фильтрация."""
        queryset = super().get_queryset()

        # Фильтр по товару
        product_id = self.request.query_params.get('product_id')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        # Фильтр по дате (от)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(date__gte=date_from)

        # Фильтр по дате (до)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(date__lte=date_to)

        return queryset

    @transaction.atomic
    def create(self, request):
        """
        Создать производственную партию.

        POST /api/products/production-batches/
        Body: {
            "product_id": 1,
            "input_type": "quantity",  // или "suzerain"
            "quantity": 200,           // если input_type=quantity
            "suzerain_quantity": 2.0,  // если input_type=suzerain
            "date": "2026-01-02",
            "notes": "Производство"
        }
        """
        # Извлекаем product_id
        product_id = request.data.get('product_id')
        if not product_id:
            return Response(
                {'error': 'Укажите product_id'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ProductionBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        input_type = serializer.validated_data['input_type']
        date_val = serializer.validated_data['date']
        notes = serializer.validated_data.get('notes', '')

        try:
            if input_type == 'quantity':
                quantity = serializer.validated_data['quantity']
                batch = ProductionService.create_batch_from_quantity(
                    product_id=product_id,
                    quantity=quantity,
                    date=date_val,
                    notes=notes
                )
            else:
                suzerain_quantity = serializer.validated_data['suzerain_quantity']
                batch = ProductionService.create_batch_from_suzerain(
                    product_id=product_id,
                    suzerain_quantity=suzerain_quantity,
                    date=date_val,
                    notes=notes
                )

            output = ProductionBatchSerializer(batch)
            return Response(output.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# =============================================================================
# PRODUCT IMAGE VIEWSET
# =============================================================================

class ProductImageViewSet(viewsets.ModelViewSet):
    """
    Изображения товаров.

    - Только админ
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = ProductImage.objects.all().select_related('product')
    serializer_class = ProductImageSerializer

    def create(self, request):
        """Создать изображение."""
        product_id = request.data.get('product_id')
        image = request.FILES.get('image')
        order = request.data.get('order', 0)

        if not product_id or not image:
            return Response(
                {'error': 'product_id и image обязательны'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            product = Product.objects.get(id=product_id)

            # Проверка лимита
            existing_count = ProductImage.objects.filter(product=product).count()
            if existing_count >= 3:
                return Response(
                    {'error': 'Максимум 3 изображения на товар'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            product_image = ProductImage.objects.create(
                product=product,
                image=image,
                order=order
            )

            serializer = ProductImageSerializer(product_image)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Product.DoesNotExist:
            return Response(
                {'error': 'Товар не найден'},
                status=status.HTTP_404_NOT_FOUND
            )


# =============================================================================
# PARTNER EXPENSE VIEWSET
# =============================================================================

class PartnerExpenseViewSet(viewsets.ModelViewSet):
    """
    Расходы партнёров.

    - Только партнёр может создавать свои расходы
    - Админ может видеть все расходы партнёров
    """

    permission_classes = [IsAuthenticated, IsAdminOrPartner]
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return PartnerExpenseCreateSerializer
        return PartnerExpenseListSerializer

    def get_queryset(self):
        """Фильтрация."""
        # ✅ Защита от drf-spectacular schema generation
        if getattr(self, 'swagger_fake_view', False):
            return PartnerExpense.objects.none()
        
        if self.request.user.role == 'admin':
            # Админ видит все расходы
            queryset = PartnerExpense.objects.all().select_related('partner')
        else:
            # Партнёр видит только свои
            queryset = PartnerExpense.objects.filter(partner=self.request.user)

        # Фильтр по дате
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(date__lte=date_to)

        return queryset.order_by('-date')

    def create(self, request):
        """Создать расход партнёра."""
        # Только партнёр может создавать свои расходы
        if request.user.role != 'partner':
            return Response(
                {'error': 'Только партнёры могут создавать расходы'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        expense = PartnerExpense.objects.create(
            partner=request.user,
            **serializer.validated_data
        )

        output = PartnerExpenseListSerializer(expense)
        return Response(output.data, status=status.HTTP_201_CREATED)


# =============================================================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ
# =============================================================================

class ProductExpenseRelationViewSet(viewsets.ModelViewSet):
    """
    УСТАРЕЛО! Для обратной совместимости.
    Используйте ProductRecipeViewSet вместо этого.
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = ProductExpenseRelation.objects.all().select_related('product', 'expense')
    serializer_class = ProductExpenseRelationSerializer
    pagination_class = StandardPagination