# apps/reports/views.py - ПОЛНАЯ ВЕРСИЯ v2.0
"""
Views для reports согласно ТЗ v2.0.

API ENDPOINTS:
- GET /api/reports/statistics/ - Статистика с круговой диаграммой
- GET /api/reports/store-history/{store_id}/ - История магазина
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from stores.models import Store
from .serializers import ReportFiltersSerializer, StoreHistoryFiltersSerializer
from .services import ReportService, ReportFilters, TimePeriod


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