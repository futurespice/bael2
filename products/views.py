# apps/products/views.py
"""
Views для модуля products.

Endpoint'ы:
- /api/products/ — CRUD товаров
- /api/expenses/ — CRUD расходов
- /api/recipes/ — CRUD рецептов (котловой метод)
- /api/accounting/dynamic/ — Экран "Динамичный учёт"
- /api/accounting/static/ — Экран "Статичный учёт"
- /api/accounting/cost-table/ — Таблица себестоимости
- /api/production/ — Учёт производства
- /api/bonuses/ — История бонусов
- /api/defective-products/ — Бракованные товары
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.db.models import Sum, F
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import viewsets, status, serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, inline_serializer
from drf_spectacular.types import OpenApiTypes

from .models import (
    Product,
    ProductImage,
    Expense,
    Recipe,
    ProductExpenseRelation,
    ProductCostSnapshot,
    ProductionRecord,
    ProductionItem,
    MechanicalExpenseEntry,
    BonusHistory,
    StoreProductCounter,
    DefectiveProduct,
    ExpenseType,
    AccountingMode,
    ExpenseState,
)
from .serializers import (
    ProductListSerializer,
    ProductDetailSerializer,
    ProductCreateSerializer,
    ExpenseListSerializer,
    ExpenseDetailSerializer,
    ExpenseCreateSerializer,
    RecipeSerializer,
    RecipeCreateSerializer,
    ProductCostSnapshotSerializer,
    CostTableSerializer,
    ProductionRecordSerializer,
    ProductionItemSerializer,
    MechanicalExpenseEntrySerializer,
    BonusHistorySerializer,
    BonusStatusSerializer,
    StoreProductCounterSerializer,
    DefectiveProductSerializer,
    DefectiveProductCreateSerializer,
    ProductExpenseRelationSerializer,
    ProductionFinanceSummarySerializer,
)
from .services import (
    CostCalculator,
    RecipeService,
    BonusService,
    AccountingService,
)
from users.permissions import IsAdminUser, IsPartnerUser


# =============================================================================
# INPUT SERIALIZERS (для drf-spectacular)
# =============================================================================

class AddRecipeInputSerializer(drf_serializers.Serializer):
    """Input для добавления рецепта к товару."""
    expense_id = drf_serializers.IntegerField(help_text="ID расхода (ингредиента)")
    ingredient_amount = drf_serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        help_text="Количество ингредиента (например, 50 кг)"
    )
    output_quantity = drf_serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        help_text="Количество продукции (например, 5000 шт)"
    )


class ApplyMarkupInputSerializer(drf_serializers.Serializer):
    """Input для применения наценки."""
    markup_percentage = drf_serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Процент наценки (0-1000)"
    )


class AddProductionItemInputSerializer(drf_serializers.Serializer):
    """Input для добавления товара в производство."""
    product_id = drf_serializers.IntegerField()
    quantity_produced = drf_serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=0
    )
    suzerain_amount = drf_serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=0
    )


class FromSuzerainInputSerializer(drf_serializers.Serializer):
    """Input для расчёта от Сюзерена."""
    product_id = drf_serializers.IntegerField(help_text="ID товара")
    suzerain_amount = drf_serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        help_text="Количество Сюзерена (кг)"
    )


class AddMechanicalExpenseInputSerializer(drf_serializers.Serializer):
    """Input для добавления механического расхода."""
    expense_id = drf_serializers.IntegerField()
    amount_spent = drf_serializers.DecimalField(max_digits=12, decimal_places=2)
    comment = drf_serializers.CharField(required=False, allow_blank=True, default='')


class AccountingDynamicResponseSerializer(drf_serializers.Serializer):
    """Response для экрана Динамичный учёт."""
    expenses = ExpenseListSerializer(many=True)
    cost_table = CostTableSerializer(many=True)


class AccountingStaticResponseSerializer(drf_serializers.Serializer):
    """Response для экрана Статичный учёт."""
    expenses = ExpenseListSerializer(many=True)
    monthly_total = drf_serializers.CharField()
    daily_total = drf_serializers.CharField()


# =============================================================================
# EXPENSE VIEWS
# =============================================================================

@extend_schema_view(
    list=extend_schema(summary="Список расходов", tags=["Расходы"]),
    retrieve=extend_schema(summary="Детали расхода", tags=["Расходы"]),
    create=extend_schema(summary="Создать расход", tags=["Расходы"]),
    update=extend_schema(summary="Обновить расход", tags=["Расходы"]),
    partial_update=extend_schema(summary="Частично обновить расход", tags=["Расходы"]),
    destroy=extend_schema(summary="Удалить расход", tags=["Расходы"]),
)
class ExpenseViewSet(viewsets.ModelViewSet):
    """
    CRUD для расходов.

    Доступ: только Admin.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Expense.objects.all().order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return ExpenseListSerializer
        if self.action == 'create':
            return ExpenseCreateSerializer
        return ExpenseDetailSerializer

    @extend_schema(
        summary="Физические расходы (ингредиенты)",
        description="Возвращает расходы для экрана 'Динамичный учёт'",
        tags=["Расходы"]
    )
    @action(detail=False, methods=['get'])
    def physical(self, request):
        """Только физические расходы (ингредиенты)."""
        expenses = self.queryset.filter(
            expense_type=ExpenseType.PHYSICAL,
            is_active=True
        )
        serializer = ExpenseListSerializer(expenses, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Накладные расходы",
        description="Возвращает расходы для экрана 'Статичный учёт'",
        tags=["Расходы"]
    )
    @action(detail=False, methods=['get'])
    def overhead(self, request):
        """Только накладные расходы."""
        expenses = self.queryset.filter(
            expense_type=ExpenseType.OVERHEAD,
            is_active=True
        )
        serializer = ExpenseListSerializer(expenses, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Динамичные расходы",
        description="Расходы, зависящие от объёма производства",
        tags=["Расходы"]
    )
    @action(detail=False, methods=['get'])
    def dynamic(self, request):
        """Расходы для экрана 'Динамичный учёт'."""
        expenses = AccountingService.get_dynamic_expenses()
        serializer = ExpenseListSerializer(expenses, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Статичные расходы",
        description="Фиксированные расходы (аренда, зарплата и т.д.)",
        tags=["Расходы"]
    )
    @action(detail=False, methods=['get'])
    def static(self, request):
        """Расходы для экрана 'Статичный учёт'."""
        expenses = AccountingService.get_static_expenses()
        serializer = ExpenseListSerializer(expenses, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Деактивировать расход",
        tags=["Расходы"],
        responses={200: inline_serializer(
            name='DeactivateResponse',
            fields={'status': drf_serializers.CharField()}
        )}
    )
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def deactivate(self, request, pk=None):
        """Деактивация расхода (мягкое удаление)."""
        expense = self.get_object()
        expense.is_active = False
        expense.save(update_fields=['is_active', 'updated_at'])

        # Помечаем снапшоты как устаревшие
        ProductCostSnapshot.objects.all().update(is_outdated=True)

        return Response({'status': 'deactivated'})


# =============================================================================
# PRODUCT VIEWS
# =============================================================================

@extend_schema_view(
    list=extend_schema(summary="Список товаров", tags=["Товары"]),
    retrieve=extend_schema(summary="Детали товара", tags=["Товары"]),
    create=extend_schema(summary="Создать товар", tags=["Товары"]),
    update=extend_schema(summary="Обновить товар", tags=["Товары"]),
    partial_update=extend_schema(summary="Частично обновить товар", tags=["Товары"]),
    destroy=extend_schema(summary="Удалить товар", tags=["Товары"]),
)
class ProductViewSet(viewsets.ModelViewSet):
    """
    CRUD для товаров.

    Доступ:
    - Чтение: все авторизованные
    - Создание/редактирование/удаление: только Admin

    Особенность: цена отображается в зависимости от роли:
    - Админ видит себестоимость
    - Партнёр/Магазин видят итоговую цену с наценкой
    """
    queryset = Product.objects.prefetch_related(
        'images',
        'recipes__expense',
        'expense_relations__expense'
    ).order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        if self.action == 'create':
            return ProductCreateSerializer
        return ProductDetailSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """Фильтрация по активности."""
        qs = super().get_queryset()

        # Партнёры и магазины видят только активные товары
        if hasattr(self.request, 'user') and self.request.user.is_authenticated:
            if getattr(self.request.user, 'role', None) in ['partner', 'store']:
                qs = qs.filter(is_active=True)

        return qs

    @extend_schema(
        summary="Добавить рецепт к товару",
        description="Добавляет ингредиент с 'котловым' методом расчёта",
        tags=["Товары"],
        request=AddRecipeInputSerializer,
        responses={201: RecipeSerializer}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdminUser])
    @transaction.atomic
    def add_recipe(self, request, pk=None):
        """Добавить рецепт к товару (котловой метод)."""
        product = self.get_object()

        serializer = AddRecipeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        expense = get_object_or_404(Expense, id=data['expense_id'])

        try:
            recipe = RecipeService.create_recipe(
                product=product,
                expense=expense,
                ingredient_amount=data['ingredient_amount'],
                output_quantity=data['output_quantity']
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        result_serializer = RecipeSerializer(recipe)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Получить рецепты товара",
        tags=["Товары"],
        responses={200: RecipeSerializer(many=True)}
    )
    @action(detail=True, methods=['get'])
    def recipes(self, request, pk=None):
        """Получить все рецепты товара."""
        product = self.get_object()
        recipes_data = RecipeService.get_product_recipes(product)
        return Response(recipes_data)

    @extend_schema(
        summary="Применить наценку",
        description="Устанавливает процент наценки и пересчитывает итоговую цену",
        tags=["Товары"],
        request=ApplyMarkupInputSerializer,
        responses={200: inline_serializer(
            name='ApplyMarkupResponse',
            fields={
                'id': drf_serializers.IntegerField(),
                'name': drf_serializers.CharField(),
                'cost_price': drf_serializers.CharField(),
                'markup_percentage': drf_serializers.CharField(),
                'final_price': drf_serializers.CharField(),
            }
        )}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdminUser])
    @transaction.atomic
    def apply_markup(self, request, pk=None):
        """Применить наценку к товару."""
        product = self.get_object()

        serializer = ApplyMarkupInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        markup = serializer.validated_data['markup_percentage']

        if markup < 0 or markup > 1000:
            return Response(
                {'error': 'markup_percentage должен быть числом от 0 до 1000'},
                status=status.HTTP_400_BAD_REQUEST
            )

        product = CostCalculator.update_product_cost_and_price(product, markup)

        return Response({
            'id': product.id,
            'name': product.name,
            'cost_price': str(product.cost_price),
            'markup_percentage': str(product.markup_percentage),
            'final_price': str(product.final_price),
        })

    @extend_schema(
        summary="Пересчитать себестоимость",
        description="Пересчитывает себестоимость товара на основе рецептов",
        tags=["Товары"],
        responses={200: ProductDetailSerializer}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdminUser])
    @transaction.atomic
    def recalculate_cost(self, request, pk=None):
        """Пересчитать себестоимость товара."""
        product = self.get_object()
        product = CostCalculator.update_product_cost_and_price(product)

        serializer = ProductDetailSerializer(product, context={'request': request})
        return Response(serializer.data)

    # Legacy endpoint для обратной совместимости
    @extend_schema(
        summary="Добавить связь с расходом (legacy)",
        description="DEPRECATED: Используйте add_recipe",
        tags=["Товары"],
        deprecated=True
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdminUser])
    @transaction.atomic
    def add_expense_relation(self, request, pk=None):
        """Добавить связь с расходом (legacy)."""
        product = self.get_object()
        expense_id = request.data.get('expense_id')
        proportion = request.data.get('proportion', 0)

        expense = get_object_or_404(Expense, id=expense_id)

        relation, created = ProductExpenseRelation.objects.update_or_create(
            product=product,
            expense=expense,
            defaults={'proportion': Decimal(str(proportion))}
        )

        # Пересчитываем себестоимость
        CostCalculator.update_product_cost_and_price(product)

        serializer = ProductExpenseRelationSerializer(relation)
        return Response(serializer.data)


# =============================================================================
# RECIPE VIEWS
# =============================================================================

@extend_schema_view(
    list=extend_schema(summary="Список рецептов", tags=["Рецепты"]),
    retrieve=extend_schema(summary="Детали рецепта", tags=["Рецепты"]),
    create=extend_schema(summary="Создать рецепт", tags=["Рецепты"]),
    update=extend_schema(summary="Обновить рецепт", tags=["Рецепты"]),
    partial_update=extend_schema(summary="Частично обновить рецепт", tags=["Рецепты"]),
    destroy=extend_schema(summary="Удалить рецепт", tags=["Рецепты"]),
)
class RecipeViewSet(viewsets.ModelViewSet):
    """
    CRUD для рецептов (котловой метод).

    Доступ: только Admin.

    Пользователь вводит:
    - ingredient_amount: 50 кг муки
    - output_quantity: 5000 булочек

    Пропорция вычисляется автоматически.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Recipe.objects.select_related('product', 'expense').order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return RecipeCreateSerializer
        return RecipeSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        """Создание с пересчётом себестоимости."""
        recipe = serializer.save()
        CostCalculator.update_product_cost_and_price(recipe.product)

    @transaction.atomic
    def perform_update(self, serializer):
        """Обновление с пересчётом себестоимости."""
        recipe = serializer.save()
        CostCalculator.update_product_cost_and_price(recipe.product)

    @transaction.atomic
    def perform_destroy(self, instance):
        """Удаление с пересчётом себестоимости."""
        product = instance.product
        instance.delete()
        CostCalculator.update_product_cost_and_price(product)


# =============================================================================
# ACCOUNTING VIEWS (Динамичный / Статичный учёт)
# =============================================================================

class AccountingDynamicView(APIView):
    """
    GET /api/accounting/dynamic/

    Возвращает данные для экрана "Динамичный учёт":
    - Список ингредиентов
    - Таблица товаров с себестоимостью
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        summary="Экран 'Динамичный учёт'",
        description="Ингредиенты + таблица товаров с себестоимостью",
        tags=["Учёт"],
        responses={200: AccountingDynamicResponseSerializer}
    )
    def get(self, request):
        # Ингредиенты
        expenses = AccountingService.get_dynamic_expenses()
        expenses_data = ExpenseListSerializer(expenses, many=True).data

        # Таблица себестоимости
        cost_table = AccountingService.get_cost_table_data()

        return Response({
            'expenses': expenses_data,
            'cost_table': cost_table,
        })


class AccountingStaticView(APIView):
    """
    GET /api/accounting/static/

    Возвращает данные для экрана "Статичный учёт":
    - Список накладных расходов
    - Итоговая сумма за месяц/день
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        summary="Экран 'Статичный учёт'",
        description="Накладные расходы (аренда, зарплата и т.д.)",
        tags=["Учёт"],
        responses={200: AccountingStaticResponseSerializer}
    )
    def get(self, request):
        expenses = AccountingService.get_static_expenses()
        expenses_data = ExpenseListSerializer(expenses, many=True).data

        # Итоговые суммы
        monthly_total = sum(
            e.monthly_amount or Decimal('0')
            for e in expenses
            if e.state == ExpenseState.AUTOMATIC
        )
        daily_total = (monthly_total / Decimal('30')).quantize(Decimal('0.01'))

        return Response({
            'expenses': expenses_data,
            'monthly_total': str(monthly_total),
            'daily_total': str(daily_total),
        })


class CostTableView(APIView):
    """
    GET /api/accounting/cost-table/

    Возвращает таблицу себестоимости:
    | Название | Наценка | Себ-сть | Расход | Доход |
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        summary="Таблица себестоимости",
        description="Для экрана 'Динамичный учёт' → секция 'Товары'",
        tags=["Учёт"],
        responses={200: CostTableSerializer(many=True)}
    )
    def get(self, request):
        cost_table = AccountingService.get_cost_table_data()
        serializer = CostTableSerializer(cost_table, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(summary="Список кеша себестоимости", tags=["Учёт"]),
    retrieve=extend_schema(summary="Детали кеша себестоимости", tags=["Учёт"]),
)
class CostSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Кеш себестоимости товаров (только чтение).
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = ProductCostSnapshot.objects.select_related('product').order_by('product__name')
    serializer_class = ProductCostSnapshotSerializer

    @extend_schema(
        summary="Пересчитать все снапшоты",
        description="Обновляет кеш себестоимости для всех товаров",
        tags=["Учёт"],
        responses={200: inline_serializer(
            name='RecalculateSnapshotsResponse',
            fields={
                'status': drf_serializers.CharField(),
                'updated_count': drf_serializers.IntegerField()
            }
        )}
    )
    @action(detail=False, methods=['post'])
    @transaction.atomic
    def recalculate_all(self, request):
        """Пересчитать все снапшоты."""
        count = CostCalculator.bulk_update_snapshots()
        return Response({
            'status': 'success',
            'updated_count': count
        })


# =============================================================================
# PRODUCTION VIEWS
# =============================================================================

@extend_schema_view(
    list=extend_schema(summary="Список записей производства", tags=["Производство"]),
    retrieve=extend_schema(summary="Детали записи производства", tags=["Производство"]),
    create=extend_schema(summary="Создать запись производства", tags=["Производство"]),
    update=extend_schema(summary="Обновить запись производства", tags=["Производство"]),
    partial_update=extend_schema(summary="Частично обновить запись", tags=["Производство"]),
    destroy=extend_schema(summary="Удалить запись производства", tags=["Производство"]),
)
class ProductionRecordViewSet(viewsets.ModelViewSet):
    """
    Записи производства (день производства).

    Доступ:
    - Партнёр: создаёт и редактирует свои записи
    - Админ: видит все записи
    """
    serializer_class = ProductionRecordSerializer
    permission_classes = [IsAuthenticated]
    queryset = ProductionRecord.objects.select_related('partner').prefetch_related(
        'items__product',
        'mechanical_entries__expense'
    ).order_by('-date')

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        if user.role == 'admin' or user.is_superuser:
            return qs
        if user.role == 'partner':
            return qs.filter(partner=user)

        return qs.none()

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsPartnerUser()]
        return [IsAuthenticated()]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """Создание или получение записи на дату."""
        date_str = request.data.get('date', str(date.today()))
        partner = request.user

        record, created = ProductionRecord.objects.get_or_create(
            partner=partner,
            date=date_str
        )

        serializer = self.get_serializer(record)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(serializer.data, status=status_code)

    @extend_schema(
        summary="Добавить товар в таблицу",
        tags=["Производство"],
        request=AddProductionItemInputSerializer,
        responses={200: ProductionItemSerializer}
    )
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def add_item(self, request, pk=None):
        """Добавить товар в таблицу производства."""
        record = self.get_object()

        serializer = AddProductionItemInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        product = get_object_or_404(Product, id=data['product_id'])

        item, created = ProductionItem.objects.update_or_create(
            record=record,
            product=product,
            defaults={
                'quantity_produced': data['quantity_produced'],
                'suzerain_amount': data['suzerain_amount']
            }
        )

        # Расчёт себестоимости
        CostCalculator.calculate_production_item(item)

        result_serializer = ProductionItemSerializer(item)
        return Response(result_serializer.data)

    @extend_schema(
        summary="Расчёт от Сюзерена",
        description="Рассчитывает количество товара по объёму главного ингредиента",
        tags=["Производство"],
        request=FromSuzerainInputSerializer,
        responses={200: inline_serializer(
            name='FromSuzerainResponse',
            fields={
                'message': drf_serializers.CharField(),
                'created': drf_serializers.BooleanField(),
                'item': ProductionItemSerializer(),
                'quantity_produced': drf_serializers.CharField(),
                'cost_price_per_unit': drf_serializers.CharField(),
                'total_cost': drf_serializers.CharField(),
                'net_profit': drf_serializers.CharField(),
            }
        )}
    )
    @action(detail=True, methods=['post'], url_path='from-suzerain')
    @transaction.atomic
    def from_suzerain(self, request, pk=None):
        """Расчёт от Сюзерена."""
        record = self.get_object()

        serializer = FromSuzerainInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        suzerain_amount = data['suzerain_amount']
        if suzerain_amount <= 0:
            return Response(
                {'error': 'suzerain_amount должен быть положительным числом'},
                status=status.HTTP_400_BAD_REQUEST
            )

        product = get_object_or_404(Product, id=data['product_id'])

        # Расчёт количества по Сюзерену
        quantity_produced = CostCalculator._calculate_quantity_from_suzerain(
            product=product,
            suzerain_amount=suzerain_amount
        )

        if quantity_produced <= 0:
            return Response(
                {'error': 'Не удалось рассчитать количество: нет рецепта с Сюзереном'},
                status=status.HTTP_400_BAD_REQUEST
            )

        item, created = ProductionItem.objects.update_or_create(
            record=record,
            product=product,
            defaults={
                'suzerain_amount': suzerain_amount,
                'quantity_produced': quantity_produced,
            }
        )

        CostCalculator.calculate_production_item(item)

        result_serializer = ProductionItemSerializer(item)
        return Response({
            'message': 'Расчёт от Сюзерена выполнен',
            'created': created,
            'item': result_serializer.data,
            'quantity_produced': str(quantity_produced),
            'cost_price_per_unit': str(item.cost_price),
            'total_cost': str(item.total_cost),
            'net_profit': str(item.net_profit),
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @extend_schema(
        summary="Добавить механический расход",
        tags=["Производство"],
        request=AddMechanicalExpenseInputSerializer,
        responses={200: MechanicalExpenseEntrySerializer}
    )
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def add_mechanical_expense(self, request, pk=None):
        """Добавить механический расход (солярка, обеды)."""
        record = self.get_object()

        serializer = AddMechanicalExpenseInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        expense = get_object_or_404(
            Expense,
            id=data['expense_id'],
            state=ExpenseState.MECHANICAL
        )

        entry, created = MechanicalExpenseEntry.objects.update_or_create(
            record=record,
            expense=expense,
            defaults={
                'amount_spent': data['amount_spent'],
                'comment': data['comment']
            }
        )

        # Пересчитываем все строки
        CostCalculator.recalculate_all_items(record)

        result_serializer = MechanicalExpenseEntrySerializer(entry)
        return Response(result_serializer.data)

    @extend_schema(
        summary="Пересчитать все позиции",
        tags=["Производство"],
        responses={200: ProductionRecordSerializer}
    )
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def recalculate(self, request, pk=None):
        """Пересчитать себестоимость всех позиций."""
        record = self.get_object()
        CostCalculator.recalculate_all_items(record)
        serializer = self.get_serializer(record)
        return Response(serializer.data)


# =============================================================================
# BONUS VIEWS
# =============================================================================

@extend_schema_view(
    list=extend_schema(summary="История бонусов", tags=["Бонусы"]),
    retrieve=extend_schema(summary="Детали бонуса", tags=["Бонусы"]),
)
class BonusViewSet(viewsets.ReadOnlyModelViewSet):
    """
    История бонусов (только чтение).

    Правило: каждый 21-й товар бесплатно.
    """
    serializer_class = BonusHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = BonusHistory.objects.select_related(
            'store', 'partner', 'product', 'order'
        ).order_by('-created_at')

        if user.role == 'admin':
            return queryset
        elif user.role == 'partner':
            return queryset.filter(partner=user)
        elif user.role == 'store':
            return queryset.filter(store__selections__user=user)

        return queryset.none()

    @extend_schema(
        summary="Статус бонуса для товара",
        tags=["Бонусы"],
        parameters=[
            OpenApiParameter("store_id", OpenApiTypes.INT, required=True),
            OpenApiParameter("product_id", OpenApiTypes.INT, required=True),
        ],
        responses={200: BonusStatusSerializer}
    )
    @action(detail=False, methods=['get'])
    def status(self, request):
        """Получить статус бонуса для товара."""
        store_id = request.query_params.get('store_id')
        product_id = request.query_params.get('product_id')

        if not store_id or not product_id:
            return Response(
                {'error': 'store_id и product_id обязательны'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from stores.models import Store

        store = get_object_or_404(Store, id=store_id)
        product = get_object_or_404(Product, id=product_id)

        # Определяем партнёра
        if request.user.role == 'partner':
            partner = request.user
        else:
            return Response(
                {'error': 'Только партнёр может проверить статус бонуса'},
                status=status.HTTP_403_FORBIDDEN
            )

        bonus_status = BonusService.get_bonus_status(store, partner, product)
        serializer = BonusStatusSerializer(bonus_status)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(summary="Счётчики товаров", tags=["Бонусы"]),
    retrieve=extend_schema(summary="Детали счётчика", tags=["Бонусы"]),
)
class StoreProductCounterViewSet(viewsets.ReadOnlyModelViewSet):
    """Счётчики товаров для бонусов."""
    serializer_class = StoreProductCounterSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = StoreProductCounter.objects.select_related(
            'store', 'partner', 'product'
        ).order_by('-total_count')

        if user.role == 'admin':
            return queryset
        elif user.role == 'partner':
            return queryset.filter(partner=user)

        return queryset.none()


# =============================================================================
# DEFECTIVE PRODUCT VIEWS
# =============================================================================

@extend_schema_view(
    list=extend_schema(summary="Список бракованных товаров", tags=["Брак"]),
    retrieve=extend_schema(summary="Детали брака", tags=["Брак"]),
    create=extend_schema(summary="Сообщить о браке", tags=["Брак"]),
)
class DefectiveProductViewSet(viewsets.ModelViewSet):
    """
    CRUD для бракованных товаров.

    Доступ:
    - Создание: Партнёр
    - Подтверждение/отклонение: Админ
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = DefectiveProduct.objects.select_related(
            'partner', 'product'
        ).order_by('-created_at')

        if user.role == 'admin':
            return queryset
        elif user.role == 'partner':
            return queryset.filter(partner=user)

        return queryset.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return DefectiveProductCreateSerializer
        return DefectiveProductSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated(), IsPartnerUser()]
        elif self.action in ['update', 'partial_update', 'destroy', 'confirm', 'reject']:
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated()]

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(partner=self.request.user)

    @extend_schema(
        summary="Подтвердить брак",
        tags=["Брак"],
        responses={200: inline_serializer(
            name='ConfirmDefectResponse',
            fields={'status': drf_serializers.CharField()}
        )}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdminUser])
    @transaction.atomic
    def confirm(self, request, pk=None):
        """Подтвердить брак."""
        defect = self.get_object()
        defect.confirm()
        return Response({'status': 'confirmed'})

    @extend_schema(
        summary="Отклонить брак",
        tags=["Брак"],
        responses={200: inline_serializer(
            name='RejectDefectResponse',
            fields={'status': drf_serializers.CharField()}
        )}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdminUser])
    @transaction.atomic
    def reject(self, request, pk=None):
        """Отклонить заявку о браке."""
        defect = self.get_object()
        defect.reject()
        return Response({'status': 'rejected'})


# =============================================================================
# FINANCE VIEW
# =============================================================================

class ProductionFinanceView(APIView):
    """
    GET /api/products/production-finance/?record_id=XXX

    Возвращает финансовую сводку по записи производства.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Финансовая сводка производства",
        tags=["Финансы"],
        parameters=[
            OpenApiParameter("record_id", OpenApiTypes.INT, required=True)
        ],
        responses={200: ProductionFinanceSummarySerializer}
    )
    def get(self, request):
        record_id = request.query_params.get("record_id")
        if not record_id:
            return Response(
                {"detail": "record_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record = get_object_or_404(ProductionRecord, pk=record_id)

        # Проверка доступа
        if request.user.role == 'partner' and record.partner != request.user:
            return Response(
                {"detail": "Нет доступа к этой записи"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Агрегация данных
        items = record.items.all()

        total_quantity = sum(i.quantity_produced or 0 for i in items)
        ingredient_cost = sum(i.ingredient_cost or 0 for i in items)
        overhead_cost = sum(i.overhead_cost or 0 for i in items)
        total_cost = sum(i.total_cost or 0 for i in items)
        revenue = sum(i.revenue or 0 for i in items)
        net_profit = sum(i.net_profit or 0 for i in items)

        # Накладные расходы
        fixed_overhead = Expense.objects.filter(
            expense_type=ExpenseType.OVERHEAD,
            state=ExpenseState.AUTOMATIC,
            is_active=True
        ).aggregate(
            total=Coalesce(Sum(F('monthly_amount') / Decimal('30')), Decimal('0'))
        )['total']

        mechanical_overhead = MechanicalExpenseEntry.objects.filter(
            record=record
        ).aggregate(
            total=Coalesce(Sum('amount_spent'), Decimal('0'))
        )['total']

        summary = {
            'record_id': record.id,
            'date': record.date,
            'total_quantity': total_quantity,
            'ingredient_cost': ingredient_cost,
            'overhead_cost': overhead_cost,
            'total_cost': total_cost,
            'revenue': revenue,
            'net_profit': net_profit,
            'fixed_daily_overhead': fixed_overhead,
            'mechanical_daily_overhead': mechanical_overhead,
            'cost_per_unit': (total_cost / total_quantity) if total_quantity > 0 else Decimal('0'),
            'profit_per_unit': (net_profit / total_quantity) if total_quantity > 0 else Decimal('0'),
        }

        serializer = ProductionFinanceSummarySerializer(summary)
        return Response(serializer.data)
