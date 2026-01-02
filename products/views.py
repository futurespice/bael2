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
from django.db import transaction

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
)
from .permissions import IsAdmin, IsPartner, IsAdminOrPartner
from .services import (
    ProductionCalculator,
    ProductionService,
    OverheadDistributor,
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
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ProductCreateSerializer
        elif self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductListSerializer

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