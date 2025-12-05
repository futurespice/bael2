# apps/products/views.py
"""Views для products."""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Expense, Product, ProductionBatch, ProductImage
from .serializers import *
from .services import *
from .permissions import IsAdmin, IsAdminOrReadOnly


class ExpenseViewSet(viewsets.ModelViewSet):
    """
    Расходы.

    - Админ: CRUD
    - Остальные: только чтение
    """

    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    queryset = Expense.objects.all().order_by('-created_at')

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


class ProductViewSet(viewsets.ModelViewSet):
    """
    Товары.

    - Админ: CRUD
    - Партнёры/Магазины: только чтение
    """

    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    queryset = Product.objects.filter(is_active=True).order_by('name')

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ProductCreateSerializer
        elif self.action == 'list':
            return ProductListSerializer
        return ProductDetailSerializer

    def list(self, request):
        """Каталог товаров."""
        if request.user.role == 'store':
            # Для магазинов - упрощённый каталог
            catalog = ProductService.get_catalog_for_stores()
            return Response(catalog)

        # Для админа и партнёров
        queryset = self.get_queryset()
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


class ProductionBatchViewSet(viewsets.ModelViewSet):
    """
    Производство.

    - Админ: CRUD
    - Остальные: только чтение
    """

    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    queryset = ProductionBatch.objects.all().order_by('-date')

    def get_serializer_class(self):
        if self.action == 'create':
            return ProductionBatchCreateSerializer
        return ProductionBatchSerializer

    def create(self, request):
        """Записать производство (только админ)."""
        serializer = ProductionBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            batch = ProductionService.create_production_batch(
                **serializer.validated_data
            )

            detail_serializer = ProductionBatchSerializer(batch)
            return Response(
                detail_serializer.data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'])
    def by_product(self, request):
        """
        История производства товара.

        GET /api/products/production-batches/by-product/?product_id=1&limit=30
        """
        product_id = request.query_params.get('product_id')
        limit = int(request.query_params.get('limit', 30))

        if not product_id:
            return Response(
                {'error': 'Укажите product_id'},
                status=status.HTTP_400_BAD_REQUEST
            )

        history = ProductionService.get_production_history(
            product_id=int(product_id),
            limit=limit
        )

        serializer = ProductionBatchSerializer(history, many=True)
        return Response(serializer.data)


class ProductImageViewSet(viewsets.ModelViewSet):
    """
    Изображения.

    - Админ: CRUD
    - Остальные: только чтение
    """

    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    queryset = ProductImage.objects.all()
    serializer_class = ProductImageSerializer

    def destroy(self, request, pk=None):
        """Удалить изображение (только админ)."""
        image = self.get_object()
        ProductImageService.delete_image(image.id)
        return Response(status=status.HTTP_204_NO_CONTENT)