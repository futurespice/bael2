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
from users.permissions import IsPartnerUser, IsAdminUser
from django.contrib.auth import get_user_model
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
        description="Получить статистику партнёра за выбранный период или дату",
        parameters=[
            OpenApiParameter(
                name='period',
                type=str,
                enum=['day', 'week', 'month', 'year'],
                description='Период статистики (игнорируется если указаны date или date_from/date_to)',
                required=False
            ),
            OpenApiParameter(
                name='date',
                type=str,
                description='Конкретная дата (YYYY-MM-DD). Если указано, возвращает статистику за этот день.',
                required=False
            ),
            OpenApiParameter(
                name='date_from',
                type=str,
                description='Начало периода (YYYY-MM-DD)',
                required=False
            ),
            OpenApiParameter(
                name='date_to',
                type=str,
                description='Конец периода (YYYY-MM-DD)',
                required=False
            ),
        ],
        responses={
            200: PartnerStatisticsSerializer,
        }
    )
    def list(self, request):
        """Получить статистику партнёра."""
        from datetime import datetime
        from django.utils import timezone
        
        period = request.query_params.get('period', 'week')
        date_str = request.query_params.get('date')
        date_from_str = request.query_params.get('date_from')
        date_to_str = request.query_params.get('date_to')
        
        date_from = None
        date_to = None
        
        # Приоритет: date > date_from/date_to > period
        try:
            if date_str:
                # Конкретный день
                specific_date = datetime.strptime(date_str, '%Y-%m-%d')
                date_from = timezone.make_aware(datetime.combine(specific_date.date(), datetime.min.time()))
                date_to = timezone.make_aware(datetime.combine(specific_date.date(), datetime.max.time()))
                period = 'day'
            elif date_from_str and date_to_str:
                # Диапазон дат
                date_from = timezone.make_aware(datetime.strptime(date_from_str, '%Y-%m-%d'))
                date_to = timezone.make_aware(datetime.combine(
                    datetime.strptime(date_to_str, '%Y-%m-%d').date(), 
                    datetime.max.time()
                ))
            elif date_from_str:
                # Только начальная дата — до сегодня
                date_from = timezone.make_aware(datetime.strptime(date_from_str, '%Y-%m-%d'))
                date_to = timezone.now()
            elif date_to_str:
                # Только конечная дата — с начала времён
                date_from = timezone.make_aware(datetime(2020, 1, 1))
                date_to = timezone.make_aware(datetime.combine(
                    datetime.strptime(date_to_str, '%Y-%m-%d').date(), 
                    datetime.max.time()
                ))
            else:
                # Используем period
                if period not in ['day', 'week', 'month', 'year']:
                    return Response(
                        {'error': 'Неверный период. Используйте: day, week, month, year'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
        except ValueError as e:
            return Response(
                {'error': f'Неверный формат даты. Используйте YYYY-MM-DD. {e}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем статистику через сервис
        try:
            stats = PartnerStatisticsService.calculate_statistics(
                partner_id=request.user.id,
                period=period,
                date_from=date_from,
                date_to=date_to
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
                description='Период профиля (игнорируется если указаны date или date_from/date_to)',
                required=False
            ),
            OpenApiParameter(
                name='date',
                type=str,
                description='Конкретная дата (YYYY-MM-DD)',
                required=False
            ),
            OpenApiParameter(
                name='date_from',
                type=str,
                description='Начало периода (YYYY-MM-DD)',
                required=False
            ),
            OpenApiParameter(
                name='date_to',
                type=str,
                description='Конец периода (YYYY-MM-DD)',
                required=False
            ),
            OpenApiParameter(
                name='store_id',
                type=int,
                description='ID магазина для фильтрации',
                required=False
            ),
        ],
        responses={
            200: PartnerProfileSerializer,
        }
    )
    def list(self, request):
        """Получить профиль партнёра."""
        from datetime import datetime
        from django.utils import timezone
        
        period = request.query_params.get('period', 'month')
        date_str = request.query_params.get('date')
        date_from_str = request.query_params.get('date_from')
        date_to_str = request.query_params.get('date_to')
        
        date_from = None
        date_to = None
        
        # Приоритет: date > date_from/date_to > period
        try:
            if date_str:
                # Конкретный день
                specific_date = datetime.strptime(date_str, '%Y-%m-%d')
                date_from = timezone.make_aware(datetime.combine(specific_date.date(), datetime.min.time()))
                date_to = timezone.make_aware(datetime.combine(specific_date.date(), datetime.max.time()))
                period = 'day'
            elif date_from_str and date_to_str:
                # Диапазон дат
                date_from = timezone.make_aware(datetime.strptime(date_from_str, '%Y-%m-%d'))
                date_to = timezone.make_aware(datetime.combine(
                    datetime.strptime(date_to_str, '%Y-%m-%d').date(), 
                    datetime.max.time()
                ))
            elif date_from_str:
                date_from = timezone.make_aware(datetime.strptime(date_from_str, '%Y-%m-%d'))
                date_to = timezone.now()
            elif date_to_str:
                date_from = timezone.make_aware(datetime(2020, 1, 1))
                date_to = timezone.make_aware(datetime.combine(
                    datetime.strptime(date_to_str, '%Y-%m-%d').date(), 
                    datetime.max.time()
                ))
            else:
                if period not in ['day', 'week', 'month', 'year']:
                    return Response(
                        {'error': 'Неверный период. Используйте: day, week, month, year'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
        except ValueError as e:
            return Response(
                {'error': f'Неверный формат даты. Используйте YYYY-MM-DD. {e}'},
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
                store_id=store_id,
                date_from=date_from,
                date_to=date_to
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
        from django.db.models import Count, Max

        queryset = self.get_queryset()
        store_ids = list(queryset.values_list('id', flat=True))

        # Bulk-fetch: 1 запрос вместо N
        orders_counts = dict(
            StoreOrder.objects.filter(
                store_id__in=store_ids,
                confirmed_by=request.user
            ).values('store_id').annotate(count=Count('id')).values_list('store_id', 'count')
        )

        # Bulk-fetch: 1 запрос вместо N (DebtPayment → order → store)
        last_payments = dict(
            DebtPayment.objects.filter(
                order__store_id__in=store_ids
            ).values('order__store_id').annotate(
                last_paid=Max('created_at')
            ).values_list('order__store_id', 'last_paid')
        )

        data = []
        for store in queryset:
            data.append({
                'id': store.id,
                'name': store.name,
                'inn': store.inn,
                'total_debt': str(store.total_debt),
                'paid_debt': str(store.paid_debt),
                'last_payment_date': last_payments.get(store.id),
                'orders_count': orders_counts.get(store.id, 0),
            })

        return Response(data)


# =============================================================================
# ADMIN: PARTNER STATISTICS (просмотр статистики партнёра админом)
# =============================================================================

User = get_user_model()


class AdminPartnerStatisticsViewSet(viewsets.ViewSet):
    """
    ViewSet для просмотра статистики конкретного партнёра администратором.

    **Endpoint:**
    - GET /api/reports/admin/partner-statistics/{partner_id}/

    **Описание:**
    Те же 10 показателей что и /api/reports/partners/statistics/,
    но доступно только админу и с добавочным полем `partner_name`.

    **Фильтры (все опциональны):**
    - date: конкретная дата (YYYY-MM-DD), по умолчанию — сегодня
    - date_from + date_to: диапазон дат
    - period: day/week/month/year

    **Приоритет фильтров:** date > date_from/date_to > period > default (сегодня)
    """

    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        summary="Статистика партнёра для админа",
        description="Просмотр статистики конкретного партнёра (доступно только админу)",
        parameters=[
            OpenApiParameter(
                name='date',
                type=str,
                description='Конкретная дата (YYYY-MM-DD). По умолчанию — сегодня.',
                required=False
            ),
            OpenApiParameter(
                name='date_from',
                type=str,
                description='Начало периода (YYYY-MM-DD)',
                required=False
            ),
            OpenApiParameter(
                name='date_to',
                type=str,
                description='Конец периода (YYYY-MM-DD)',
                required=False
            ),
            OpenApiParameter(
                name='period',
                type=str,
                enum=['day', 'week', 'month', 'year'],
                description='Период (игнорируется если указаны date или date_from/date_to)',
                required=False
            ),
        ],
        responses={
            200: OpenApiResponse(description="Статистика партнёра с partner_name"),
            404: OpenApiResponse(description="Партнёр не найден"),
        }
    )
    def retrieve(self, request, pk=None):
        """Получить статистику конкретного партнёра."""
        from datetime import datetime as dt
        from django.utils import timezone

        # Проверяем что партнёр существует
        try:
            partner = User.objects.get(pk=pk, role='partner')
        except User.DoesNotExist:
            return Response(
                {'error': 'Партнёр не найден'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Парсим фильтры дат
        date_str = request.query_params.get('date')
        date_from_str = request.query_params.get('date_from')
        date_to_str = request.query_params.get('date_to')
        period = request.query_params.get('period')

        date_from = None
        date_to = None

        try:
            if date_str:
                # Конкретный день
                specific_date = dt.strptime(date_str, '%Y-%m-%d')
                date_from = timezone.make_aware(dt.combine(specific_date.date(), dt.min.time()))
                date_to = timezone.make_aware(dt.combine(specific_date.date(), dt.max.time()))
                period = 'day'
            elif date_from_str and date_to_str:
                # Диапазон дат
                date_from = timezone.make_aware(dt.strptime(date_from_str, '%Y-%m-%d'))
                date_to = timezone.make_aware(dt.combine(
                    dt.strptime(date_to_str, '%Y-%m-%d').date(),
                    dt.max.time()
                ))
            elif date_from_str:
                date_from = timezone.make_aware(dt.strptime(date_from_str, '%Y-%m-%d'))
                date_to = timezone.now()
            elif date_to_str:
                date_from = timezone.make_aware(dt(2020, 1, 1))
                date_to = timezone.make_aware(dt.combine(
                    dt.strptime(date_to_str, '%Y-%m-%d').date(),
                    dt.max.time()
                ))
            elif period:
                # Используем period
                if period not in ['day', 'week', 'month', 'year']:
                    return Response(
                        {'error': 'Неверный период. Используйте: day, week, month, year'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                # По умолчанию — сегодня
                today = timezone.localdate()
                date_from = timezone.make_aware(dt.combine(today, dt.min.time()))
                date_to = timezone.make_aware(dt.combine(today, dt.max.time()))
                period = 'day'
        except ValueError as e:
            return Response(
                {'error': f'Неверный формат даты. Используйте YYYY-MM-DD. {e}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем статистику через тот же сервис
        try:
            stats = PartnerStatisticsService.calculate_statistics(
                partner_id=partner.id,
                period=period or 'day',
                date_from=date_from,
                date_to=date_to
            )

            # Добавляем partner_name
            stats['partner_name'] = partner.get_full_name()
            stats['partner_id'] = partner.id

            return Response(stats)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )