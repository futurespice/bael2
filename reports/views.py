# apps/reports/views.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Views для reports согласно ТЗ v2.0.

API ENDPOINTS:
- GET /api/reports/statistics/ - Статистика с круговой диаграммой
- GET /api/reports/store-history/{store_id}/ - История магазина
"""

from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from stores.models import Store
from .serializers import ReportFiltersSerializer, StoreHistoryFiltersSerializer, PartnerStoreSerializer, PartnerTrackerOrderSerializer, PartnerStatisticsSerializer, PartnerProfileSerializer
from .services import ReportService, ReportFilters, TimePeriod, PartnerProfileService, PartnerStatisticsService
from users.permissions import IsPartnerUser
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiResponse
from django.db.models import Q, Max, Count


@extend_schema(
    summary="Статистика (круговая диаграмма)",
    description="Получить статистику с круговой диаграммой (ТЗ v2.0)",
    parameters=[
        OpenApiParameter('period', str, enum=['day', 'week', 'month', 'half_year', 'year', 'all_time']),
        OpenApiParameter('start_date', str, description='YYYY-MM-DD'),
        OpenApiParameter('end_date', str, description='YYYY-MM-DD'),
        OpenApiParameter('store_id', int),
        OpenApiParameter('partner_id', int),
        OpenApiParameter('region_id', int),
        OpenApiParameter('city_id', int),
    ],
    responses={200: OpenApiResponse(description="Statistics response")},
    tags=['Reports']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_statistics(request: Request) -> Response:
    """
    Получить статистику с круговой диаграммой (ТЗ v2.0).

    GET /api/reports/statistics/

    Query параметры:
    - period: day, week, month, half_year, year, all_time (default: all_time)
    - start_date: YYYY-MM-DD (опционально)
    - end_date: YYYY-MM-DD (опционально)
    - store_id: int (опционально)
    - partner_id: int (опционально)
    - region_id: int (опционально)
    - city_id: int (опционально)

    Ответ:
    {
        "period": {
            "type": "month",
            "start_date": "2024-12-01",
            "end_date": "2024-12-31"
        },
        "filters": {...},
        "statistics": {
            "income": 150000.00,
            "debt": 20000.00,
            "paid_debt": 10000.00,
            "defect_amount": 5000.00,
            "expenses": 15000.00,
            "bonus_count": 50,
            "orders_count": 30,
            "products_count": 500,
            "total_balance": 110000.00,
            "profit": 130000.00
        },
        "chart_data": {
            "income": 150000.00,
            "debt": 20000.00,
            "defect": 5000.00,
            "expenses": 15000.00
        }
    }
    """
    # Валидация параметров
    serializer = ReportFiltersSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    # Формируем фильтры
    filters = ReportFilters(
        period=TimePeriod(serializer.validated_data['period']),
        start_date=serializer.validated_data.get('start_date'),
        end_date=serializer.validated_data.get('end_date'),
        store_id=serializer.validated_data.get('store_id'),
        partner_id=serializer.validated_data.get('partner_id'),
        region_id=serializer.validated_data.get('region_id'),
        city_id=serializer.validated_data.get('city_id'),
    )

    # Получаем статистику
    result = ReportService.get_statistics_summary(filters)

    return Response(result)


@extend_schema(
    summary="История магазина",
    description="История магазина с фильтрацией по дате (ТЗ v2.0)",
    parameters=[
        OpenApiParameter('start_date', str, description='YYYY-MM-DD'),
        OpenApiParameter('end_date', str, description='YYYY-MM-DD'),
    ],
    responses={200: OpenApiResponse(description="Store history response")},
    tags=['Reports']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_store_history(request: Request, store_id: int) -> Response:
    """
    История магазина с фильтрацией по дате (ТЗ v2.0).

    GET /api/reports/store-history/{store_id}/

    Query параметры (все опциональны):
    - start_date: YYYY-MM-DD (по умолчанию: с первого заказа)
    - end_date: YYYY-MM-DD (по умолчанию: сегодня)

    Примеры:
    - GET /api/reports/store-history/1/
      → За всё время

    - GET /api/reports/store-history/1/?start_date=2024-01-01
      → С 2024-01-01 до сегодня

    - GET /api/reports/store-history/1/?end_date=2024-12-31
      → С первого заказа до 2024-12-31

    - GET /api/reports/store-history/1/?start_date=2024-01-01&end_date=2024-12-31
      → Конкретный диапазон
    """
    from stores.models import Store

    # Валидация магазина
    try:
        store = Store.objects.get(pk=store_id)
    except Store.DoesNotExist:
        return Response(
            {'error': 'Магазин не найден'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Валидация дат (теперь опциональны)
    serializer = StoreHistoryFiltersSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    # Получаем историю
    history = ReportService.get_store_history(
        store=store,
        start_date=serializer.validated_data.get('start_date'),  # ✅ Может быть None
        end_date=serializer.validated_data.get('end_date')  # ✅ Может быть None
    )

    return Response(history)


# =============================================================================
# PARTNER STATISTICS (v3.0)
# =============================================================================

class PartnerStatisticsViewSet(viewsets.ViewSet):
    """
    ViewSet для статистики партнёра (10 показателей).

    **Endpoint:**
    - GET /api/partners/statistics/?period=week

    **Периоды:**
    - day: день
    - week: неделя
    - month: месяц
    - year: год

    **Ответ:** 10 показателей статистики
    """

    permission_classes = [IsAuthenticated, IsPartnerUser]

    @extend_schema(
        summary="Статистика партнёра (10 показателей)",
        description="Получить статистику партнёра за выбранный период",
        parameters=[
            OpenApiParameter(
                name='period',
                type=str,
                enum=['day', 'week', 'month', 'year'],
                description='Период статистики',
                required=True
            ),
        ],
        responses={
            200: PartnerStatisticsSerializer,
        }
    )
    def list(self, request):
        """Получить статистику партнёра."""
        period = request.query_params.get('period', 'week')

        if period not in ['day', 'week', 'month', 'year']:
            return Response(
                {'error': 'Неверный период. Используйте: day, week, month, year'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем статистику через сервис
        try:
            stats = PartnerStatisticsService.calculate_statistics(
                partner_id=request.user.id,
                period=period
            )

            return Response(stats)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PartnerProfileViewSet(viewsets.ViewSet):
    """
    ViewSet для профиля партнёра с историей продаж.

    **Endpoint:**
    - GET /api/partners/profile/?period=month

    **Ответ:**
    ```json
    {
        "period": "month",
        "stores": [
            {
                "store_name": "Магазин №1",
                "store_inn": "01234567890123",
                "orders": [
                    {
                        "date": "2026-01-09",
                        "product_name": "Пельмени",
                        "quantity": 20,
                        "price_per_unit": "200.00",
                        "total_amount": "4000.00"
                    }
                ],
                "total_sold": "6250.00"
            }
        ],
        "total_all_stores": "25000.00"
    }
    ```
    """

    permission_classes = [IsAuthenticated, IsPartnerUser]

    @extend_schema(
        summary="Профиль партнёра",
        description="Получить профиль партнёра с историей продаж по магазинам",
        parameters=[
            OpenApiParameter(
                name='period',
                type=str,
                enum=['day', 'week', 'month', 'year'],
                description='Период профиля',
                required=True
            ),
        ],
        responses={
            200: PartnerProfileSerializer,
        }
    )
    def list(self, request):
        """Получить профиль партнёра."""
        period = request.query_params.get('period', 'month')

        if period not in ['day', 'week', 'month', 'year']:
            return Response(
                {'error': 'Неверный период. Используйте: day, week, month, year'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Получаем store_id для фильтрации
            store_id = request.query_params.get('store_id')
            if store_id:
                store_id = int(store_id)
            
            profile = PartnerProfileService.get_profile_data(
                partner_id=request.user.id,
                period=period,
                store_id=store_id
            )

            return Response(profile)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PartnerTrackerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet для трекера партнёра с фильтрацией.

    **Endpoint:**
    - GET /api/partners/tracker/?type=preorder

    **Типы заказов:**
    - preorder: предзаказы
    - manual: ручные заказы
    - all: все заказы
    """

    permission_classes = [IsAuthenticated, IsPartnerUser]
    serializer_class = PartnerTrackerOrderSerializer

    def get_queryset(self):
        """Получить заказы партнёра."""
        from orders.models import StoreOrder
        
        # ✅ Защита от drf-spectacular schema generation
        if getattr(self, 'swagger_fake_view', False):
            return StoreOrder.objects.none()

        order_type = self.request.query_params.get('type', 'all')

        # Только заказы, подтверждённые текущим партнёром
        queryset = StoreOrder.objects.filter(
            confirmed_by=self.request.user,
            status='accepted'
        ).select_related(
            'store',
            'confirmed_by'
        ).prefetch_related(
            'items',
            'returned_items'
        ).order_by('-created_at')

        # Фильтр по типу
        if order_type == 'preorder':
            queryset = queryset.filter(order_type='preorder')
        elif order_type == 'manual':
            queryset = queryset.filter(order_type='manual')
        # 'all' - без фильтра

        return queryset

    @extend_schema(
        summary="Трекер заказов партнёра",
        description="Получить список заказов партнёра с фильтрацией",
        parameters=[
            OpenApiParameter(
                name='type',
                type=str,
                enum=['preorder', 'manual', 'all'],
                description='Тип заказа',
            ),
        ],
        responses={
            200: PartnerTrackerOrderSerializer(many=True),
        }
    )
    def list(self, request, *args, **kwargs):
        """Список заказов."""
        queryset = self.get_queryset()

        # Добавляем аннотации
        queryset = queryset.annotate(
            items_count=Count('items'),
            returned_items_count=Count('returned_items')
        )

        # Формируем ответ вручную для полного контроля
        data = []
        for order in queryset:
            data.append({
                'id': order.id,
                'store': {
                    'id': order.store.id,
                    'name': order.store.name,
                },
                'order_type': order.order_type,
                'status': order.status,
                'total_amount': str(order.total_amount),
                'debt_amount': str(order.debt_amount),
                'created_at': order.created_at,
                'accepted_at': order.accepted_at,
                'items_count': order.items_count,
                'returned_items_count': order.returned_items_count,
            })

        return Response(data)


class PartnerStoresViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet для списка магазинов партнёра с сортировкой.

    **Endpoint:**
    - GET /api/partners/stores/?sort=debt_desc

    **Сортировки:**
    - debt_desc: по долгу (убывание)
    - paid_date_desc: по дате погашения (новые первые)
    """

    permission_classes = [IsAuthenticated, IsPartnerUser]
    serializer_class = PartnerStoreSerializer

    def get_queryset(self):
        """Получить магазины партнёра."""
        from stores.models import Store
        from orders.models import StoreOrder, DebtPayment

        sort_by = self.request.query_params.get('sort', 'debt_desc')

        # Магазины, с которыми работал партнёр
        store_ids = StoreOrder.objects.filter(
            confirmed_by=self.request.user
        ).values_list('store_id', flat=True).distinct()

        queryset = Store.objects.filter(
            id__in=store_ids
        ).select_related(
            'region',
            'city'
        )

        # Сортировка
        if sort_by == 'debt_desc':
            queryset = queryset.order_by('-total_debt')
        elif sort_by == 'paid_date_desc':
            # Сортировка по последней дате погашения
            queryset = queryset.annotate(
                last_payment=Max(
                    'debt_payments__paid_at',
                    filter=Q(debt_payments__isnull=False)
                )
            ).order_by('-last_payment')

        return queryset

    @extend_schema(
        summary="Список магазинов партнёра",
        description="Получить список магазинов с сортировкой",
        parameters=[
            OpenApiParameter(
                name='sort',
                type=str,
                enum=['debt_desc', 'paid_date_desc'],
                description='Сортировка',
            ),
        ],
        responses={
            200: PartnerStoreSerializer(many=True),
        }
    )
    def list(self, request, *args, **kwargs):
        """Список магазинов."""
        from orders.models import StoreOrder, DebtPayment

        queryset = self.get_queryset()

        # Формируем ответ
        data = []
        for store in queryset:
            # Получаем количество заказов
            orders_count = StoreOrder.objects.filter(
                store=store,
                confirmed_by=request.user
            ).count()

            # Получаем последнюю дату погашения
            last_payment = DebtPayment.objects.filter(
                store=store
            ).order_by('-paid_at').first()

            data.append({
                'id': store.id,
                'name': store.name,
                'inn': store.inn,
                'total_debt': str(store.total_debt),
                'paid_debt': str(store.paid_debt),
                'last_payment_date': last_payment.paid_at if last_payment else None,
                'orders_count': orders_count,
            })

        return Response(data)