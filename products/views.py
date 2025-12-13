# apps/products/views.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Views для products.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. Добавлен PartnerExpenseViewSet (расходы партнёра)
2. Добавлен ProductExpenseRelationViewSet (связь товар-расход)
3. Добавлен эндпоинт calculate_cost для расчёта себестоимости
4. Поддержка загрузки изображений при создании товара
"""

from decimal import Decimal
from datetime import date

from django.db.models import QuerySet
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .models import (
    Expense, 
    PartnerExpense,
    Product, 
    ProductionBatch, 
    ProductImage,
    ProductExpenseRelation
)
from .serializers import (
    ExpenseSerializer,
    ExpenseCreateSerializer,
    ExpenseSummarySerializer,
    PartnerExpenseSerializer,
    PartnerExpenseCreateSerializer,
    PartnerExpenseListSerializer,
    PartnerExpenseSummarySerializer,
    ProductListSerializer,
    ProductDetailSerializer,
    ProductCreateSerializer,
    ProductUpdateMarkupSerializer,
    ProductionBatchSerializer,
    ProductionBatchCreateSerializer,
    ProductImageSerializer,
    ProductExpenseRelationSerializer,
    ProductExpenseRelationCreateSerializer,
    CostCalculationRequestSerializer,
    CostCalculationResultSerializer, ProductAdminListSerializer, ProductAdminDetailSerializer,
)
from .services import (
    ExpenseService,
    ProductService,
    ProductionService,
    ProductImageService,
)
from .permissions import IsAdmin, IsAdminOrReadOnly, IsPartner, IsPartnerOrAdmin


# =============================================================================
# PAGINATION
# =============================================================================

class StandardPagination(PageNumberPagination):
    """Стандартная пагинация."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# =============================================================================
# EXPENSE (PRODUCTION) VIEWSET
# =============================================================================

class ExpenseViewSet(viewsets.ModelViewSet):
    """
    Расходы на производство.

    - Админ: CRUD
    - Остальные: только чтение
    """

    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    queryset = Expense.objects.all().order_by('-created_at')
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ExpenseCreateSerializer
        return ExpenseSerializer

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Сводка по расходам."""
        data = ExpenseService.get_expenses_summary()
        serializer = ExpenseSummarySerializer(data)
        return Response(serializer.data)


# =============================================================================
# PARTNER EXPENSE VIEWSET (НОВОЕ v2.0)
# =============================================================================

class PartnerExpenseViewSet(viewsets.ModelViewSet):
    """
    Расходы партнёра (ТЗ v2.0).
    
    POST /api/products/partner-expenses/
    Body: {"amount": 1000, "description": "Бензин"}
    
    - Партнёр: создание, просмотр своих
    - Админ: просмотр всех
    """

    permission_classes = [IsAuthenticated, IsPartnerOrAdmin]
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        
        if user.role == 'admin':
            return PartnerExpense.objects.all().select_related('partner')
        elif user.role == 'partner':
            return PartnerExpense.objects.filter(partner=user)
        
        return PartnerExpense.objects.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return PartnerExpenseCreateSerializer
        elif self.action == 'list':
            return PartnerExpenseListSerializer
        return PartnerExpenseSerializer

    def create(self, request):
        """
        Партнёр создаёт расход.
        
        POST /api/products/partner-expenses/
        Body: {"amount": 1000, "description": "Бензин"}
        """
        if request.user.role != 'partner':
            return Response(
                {'error': 'Только партнёры могут создавать расходы'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        expense = PartnerExpense.objects.create(
            partner=request.user,
            amount=serializer.validated_data['amount'],
            description=serializer.validated_data['description'],
            date=serializer.validated_data.get('date', date.today())
        )

        output = PartnerExpenseSerializer(expense)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def my_expenses(self, request):
        """Мои расходы (только для партнёра)."""
        if request.user.role != 'partner':
            return Response(
                {'error': 'Доступно только для партнёров'},
                status=status.HTTP_403_FORBIDDEN
            )

        expenses = PartnerExpense.objects.filter(partner=request.user)
        
        # Фильтрация по датам
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if start_date:
            expenses = expenses.filter(date__gte=start_date)
        if end_date:
            expenses = expenses.filter(date__lte=end_date)

        page = self.paginate_queryset(expenses)
        if page is not None:
            serializer = PartnerExpenseListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PartnerExpenseListSerializer(expenses, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Сводка по расходам партнёров (для админа)."""
        from django.db.models import Sum, Count
        
        queryset = self.get_queryset()
        
        # Фильтрация по датам
        start_date = request.query_params.get('start_date', date.today().replace(day=1))
        end_date = request.query_params.get('end_date', date.today())
        
        queryset = queryset.filter(date__gte=start_date, date__lte=end_date)
        
        stats = queryset.aggregate(
            total_amount=Sum('amount'),
            expenses_count=Count('id')
        )
        
        data = {
            'total_amount': stats['total_amount'] or Decimal('0'),
            'expenses_count': stats['expenses_count'] or 0,
            'period_start': start_date,
            'period_end': end_date
        }
        
        serializer = PartnerExpenseSummarySerializer(data)
        return Response(serializer.data)


# =============================================================================
# PRODUCT VIEWSET
# =============================================================================

class ProductViewSet(viewsets.ModelViewSet):
    """
    Товары.

    - Админ: CRUD
    - Партнёры/Магазины: только чтение
    """

    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    queryset = Product.objects.filter(is_active=True).prefetch_related('images').order_by('name')
    pagination_class = StandardPagination

    def get_queryset(self) -> QuerySet[Product]:
        """Получение товаров (см. код выше)."""
        user = self.request.user
        queryset = Product.objects.prefetch_related('images')

        if user.role == 'admin':
            return queryset.all()

        return queryset.filter(is_active=True)

    def get_serializer_class(self):
        """Выбор сериализатора в зависимости от роли (см. код выше)."""
        user = self.request.user

        # АДМИН (с себестоимостью)
        if user.role == 'admin':
            if self.action == 'list':
                return ProductAdminListSerializer
            elif self.action in ['retrieve', 'update', 'partial_update']:
                return ProductAdminDetailSerializer
            elif self.action == 'create':
                return ProductCreateSerializer

        # ПАРТНЁР/МАГАЗИН (без себестоимости)
        else:
            if self.action == 'list':
                return ProductListSerializer
            elif self.action == 'retrieve':
                return ProductDetailSerializer

        return ProductDetailSerializer


    def list(self, request):
        """Каталог товаров."""
        if request.user.role == 'store':
            catalog = ProductService.get_catalog_for_stores()
            return Response(catalog)

        queryset = self.get_queryset()
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ProductListSerializer(
                page,
                many=True,
                context={'request': request}
            )
            return self.get_paginated_response(serializer.data)
        
        serializer = ProductListSerializer(
            queryset,
            many=True,
            context={'request': request}
        )
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Детали товара."""
        product = self.get_object()
        for_admin = request.user.role == 'admin'
        data = ProductService.get_product_details(product.id, for_admin)
        return Response(data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdmin])
    def set_markup(self, request, pk=None):
        """
        Установить наценку (только админ).

        POST /api/products/products/{id}/set-markup/
        {"markup_percentage": "15"}
        """
        product = self.get_object()
        serializer = ProductUpdateMarkupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = ProductService.update_markup(
            product.id,
            serializer.validated_data['markup_percentage']
        )

        return Response({
            'id': updated.id,
            'markup_percentage': float(updated.markup_percentage),
            'final_price': float(updated.final_price)
        })

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdmin])
    def upload_images(self, request, pk=None):
        """
        Загрузить изображения (только админ).

        POST /api/products/products/{id}/upload-images/
        FormData: images=[file1, file2, file3]
        """
        product = self.get_object()
        images = request.FILES.getlist('images')

        if not images:
            return Response(
                {'error': 'Нет изображений'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            created = ProductImageService.add_images(product.id, images)
            serializer = ProductImageSerializer(created, many=True)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdmin])
    def calculate_cost(self, request, pk=None):
        """
        Рассчитать себестоимость товара (ТЗ v2.0, требование #4).

        POST /api/products/products/{id}/calculate-cost/
        Body: {"quantity_produced": 1100, "date": "2024-12-05"}
        
        Возвращает:
        - Общие дневные расходы
        - Месячные расходы (на день)
        - Себестоимость за единицу
        - Рекомендуемая цена с наценкой
        """
        product = self.get_object()
        
        serializer = CostCalculationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        quantity = serializer.validated_data['quantity_produced']
        calc_date = serializer.validated_data.get('date', date.today())
        
        # Получаем расходы, связанные с товаром
        related_expenses = ProductExpenseRelation.objects.filter(
            product=product
        ).select_related('expense')
        
        # Расчёт дневных расходов
        total_daily = Decimal('0')
        for relation in related_expenses:
            expense = relation.expense
            if expense.is_active:
                total_daily += expense.daily_amount
        
        # Универсальные расходы (применяются ко всем товарам)
        universal_expenses = Expense.objects.filter(
            apply_type='universal',
            is_active=True
        )
        for expense in universal_expenses:
            total_daily += expense.daily_amount
        
        # Месячные расходы → дневные (делим на 30)
        total_monthly = Decimal('0')
        for relation in related_expenses:
            expense = relation.expense
            if expense.is_active:
                total_monthly += expense.monthly_amount
        
        for expense in universal_expenses:
            total_monthly += expense.monthly_amount
        
        monthly_per_day = total_monthly / Decimal('30')
        
        # Общие расходы на день
        total_expenses = total_daily + monthly_per_day
        
        # Себестоимость за единицу
        if quantity > 0:
            cost_per_unit = (total_expenses / quantity).quantize(Decimal('0.01'))
        else:
            cost_per_unit = Decimal('0')
        
        # Рекомендуемая цена с наценкой
        suggested_price = cost_per_unit * (Decimal('1') + product.markup_percentage / Decimal('100'))
        suggested_price = suggested_price.quantize(Decimal('0.01'))
        
        result = {
            'product_id': product.id,
            'product_name': product.name,
            'quantity_produced': quantity,
            'total_daily_expenses': total_daily,
            'total_monthly_expenses_per_day': monthly_per_day,
            'total_expenses': total_expenses,
            'cost_price_per_unit': cost_per_unit,
            'suggested_final_price': suggested_price,
            'current_markup_percentage': product.markup_percentage
        }
        
        output = CostCalculationResultSerializer(result)
        return Response(output.data)




# =============================================================================
# PRODUCTION VIEWSET
# =============================================================================

class ProductionBatchViewSet(viewsets.ModelViewSet):
    """
    Производственные партии.

    - Только админ
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = ProductionBatch.objects.all().select_related('product').order_by('-date')
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ProductionBatchCreateSerializer
        return ProductionBatchSerializer

    def create(self, request):
        """Создать производственную запись."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            batch = ProductionService.record_production(
                product_id=serializer.validated_data['product_id'],
                date=serializer.validated_data['date'],
                quantity=serializer.validated_data['quantity_produced'],
                notes=serializer.validated_data.get('notes', '')
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
# PRODUCT EXPENSE RELATION VIEWSET (НОВОЕ v2.0)
# =============================================================================

class ProductExpenseRelationViewSet(viewsets.ModelViewSet):
    """
    Связь товар-расход (ТЗ v2.0, требование #12).
    
    POST /api/products/product-expense-relations/
    Body: {"product": 1, "expense": 2, "proportion": 0.5}
    
    - Только админ
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = ProductExpenseRelation.objects.all().select_related('product', 'expense')
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ProductExpenseRelationCreateSerializer
        return ProductExpenseRelationSerializer

    def list(self, request):
        """Список связей."""
        product_id = request.query_params.get('product_id')
        expense_id = request.query_params.get('expense_id')

        queryset = self.get_queryset()

        if product_id:
            queryset = queryset.filter(product_id=product_id)
        if expense_id:
            queryset = queryset.filter(expense_id=expense_id)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ProductExpenseRelationSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ProductExpenseRelationSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_product(self, request):
        """
        Получить все расходы для товара.
        
        GET /api/products/product-expense-relations/by-product/?product_id=1
        """
        product_id = request.query_params.get('product_id')
        
        if not product_id:
            return Response(
                {'error': 'product_id обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )

        relations = ProductExpenseRelation.objects.filter(
            product_id=product_id
        ).select_related('expense')

        serializer = ProductExpenseRelationSerializer(relations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_expense(self, request):
        """
        Получить все товары для расхода.
        
        GET /api/products/product-expense-relations/by-expense/?expense_id=1
        """
        expense_id = request.query_params.get('expense_id')
        
        if not expense_id:
            return Response(
                {'error': 'expense_id обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )

        relations = ProductExpenseRelation.objects.filter(
            expense_id=expense_id
        ).select_related('product')

        serializer = ProductExpenseRelationSerializer(relations, many=True)
        return Response(serializer.data)
