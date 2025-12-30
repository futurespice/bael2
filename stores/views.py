# apps/stores/views.py - ИСПРАВЛЕННАЯ ВЕРСИЯ v2.0
"""
Views для stores согласно ТЗ v2.0.

КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v2.0:
1. Инвентарь скрыт при статусе "В пути" (требование #11)
2. Удалён фильтр по долгу (требование #5)
3. Добавлена пагинация

API ENDPOINTS:
1. Регионы и города (админ):
   - GET /api/regions/ - список регионов
   - POST /api/regions/ - создать регион
   - GET /api/cities/ - список городов
   - POST /api/cities/ - создать город

2. Магазины:
   - GET /api/stores/ - список магазинов (с поиском и фильтрацией)
   - POST /api/stores/ - регистрация магазина
   - GET /api/stores/{id}/ - детальная информация
   - PATCH /api/stores/{id}/ - обновление профиля
   - POST /api/stores/{id}/approve/ - одобрить (админ)
   - POST /api/stores/{id}/reject/ - отклонить (админ)
   - POST /api/stores/{id}/freeze/ - заморозить (админ)
   - POST /api/stores/{id}/unfreeze/ - разморозить (админ)

3. Выбор магазина:
   - GET /api/stores/available/ - доступные магазины для выбора
   - POST /api/stores/select/ - выбрать магазин
   - POST /api/stores/deselect/ - отменить выбор
   - GET /api/stores/current/ - текущий выбранный магазин

4. Инвентарь:
   - GET /api/stores/{id}/inventory/ - инвентарь магазина
"""

from decimal import Decimal
from typing import Any, Dict
from django.db import transaction
from django.db.models import QuerySet, Q, F  # ✅ Добавлен Q
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.core.exceptions import ValidationError
from django.utils import timezone
# ✅ ДОБАВЛЕНЫ ИМПОРТЫ drf-spectacular
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from .permissions import IsPartner

from .models import (
    Region,
    City,
    Store,
    StoreSelection,
    StoreInventory,
)
from .serializers import (
    RegionSerializer,
    CitySerializer,
    StoreSerializer,
    StoreListSerializer,
    StoreCreateSerializer,
    StoreUpdateSerializer,
    StoreSelectionSerializer,
    StoreSelectionCreateSerializer,
    StoreInventorySerializer,
    StoreInventoryListSerializer,
    StoreSearchSerializer,
    StoreApproveSerializer,
    StoreRejectSerializer,
    StoreFreezeSerializer,
    StoreUnfreezeSerializer,
)
from .services import (
    StoreService,
    StoreSelectionService,
    StoreInventoryService,
    GeographyService,
    BonusCalculationService,  # ✅ НОВОЕ v2.0
    StoreCreateData,
    StoreUpdateData,
    StoreSearchFilters,
)
from .permissions import IsAdmin, IsStore, IsAdminOrReadOnly
from orders.models import (
    StoreOrder,
    StoreOrderStatus,
    StoreOrderItem,
    OrderHistory,
    OrderType,
    DefectiveProduct,  # ✅ Статус внутри: DefectiveProduct.DefectStatus
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
# ГЕОГРАФИЯ (РЕГИОНЫ И ГОРОДА)
# =============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Список регионов",
        description="Получить список всех регионов Кыргызстана",

    ),
    create=extend_schema(
        summary="Создать регион",
        description="Создать новый регион (только админ)",

    ),
    retrieve=extend_schema(
        summary="Детали региона",
    ),
    update=extend_schema(
        summary="Обновить регион",
    ),
    partial_update=extend_schema(
        summary="Частично обновить регион",
    ),
    destroy=extend_schema(
        summary="Удалить регион",
    ),
)
class RegionViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления регионами (только админ).

    ТЗ v2.0: "Области и города управляются админом"
    """

    queryset = Region.objects.all()
    serializer_class = RegionSerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = StandardPagination

    def perform_create(self, serializer):
        """Создание региона через сервис."""
        region = GeographyService.create_region(
            name=serializer.validated_data['name'],
            created_by=self.request.user
        )
        serializer.instance = region


@extend_schema_view(
    list=extend_schema(
        summary="Список городов",
        description="Получить список всех городов",
        parameters=[
            OpenApiParameter(
                name='region',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Фильтр по региону'
            )
        ],
    ),
    create=extend_schema(
        summary="Создать город",
        description="Создать новый город (только админ)",

    ),
    retrieve=extend_schema(
        summary="Детали города",
    ),
)
class CityViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления городами (только админ).

    ТЗ v2.0: "Города управляются админом"
    """

    queryset = City.objects.select_related('region').all()
    serializer_class = CitySerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = StandardPagination
    filterset_fields = ['region']

    def perform_create(self, serializer):
        """Создание города через сервис."""
        city = GeographyService.create_city(
            region_id=serializer.validated_data['region'].id,
            name=serializer.validated_data['name'],
            created_by=self.request.user
        )
        serializer.instance = city


# =============================================================================
# МАГАЗИНЫ
# =============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Список магазинов",
        description="Получить список магазинов с поиском и фильтрацией",
        parameters=[
            OpenApiParameter('search', OpenApiTypes.STR, description='Поиск по ИНН, названию, городу'),
            OpenApiParameter('region_id', OpenApiTypes.INT, description='Фильтр по региону'),
            OpenApiParameter('city_id', OpenApiTypes.INT, description='Фильтр по городу'),
            OpenApiParameter('is_active', OpenApiTypes.BOOL, description='Фильтр по активности'),
        ],

    ),
    create=extend_schema(
        summary="Регистрация магазина",
        description="Зарегистрировать новый магазин",

    ),
    retrieve=extend_schema(
        summary="Детали магазина",

    ),
    update=extend_schema(
        summary="Обновить магазин",

    ),
    partial_update=extend_schema(
        summary="Частично обновить магазин",

    ),
)
class StoreViewSet(viewsets.ModelViewSet):
    """
    ViewSet для работы с магазинами.

    ДОСТУП:
    - Админ: все операции
    - Партнёр: чтение, поиск, фильтрация
    - Магазин: регистрация, обновление своего профиля, чтение
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self) -> QuerySet[Store]:
        """
        Получение списка магазинов в зависимости от роли.

        ✅ ИСПРАВЛЕНО: Добавлена защита от swagger_fake_view
        """
        # Для Swagger документации
        if getattr(self, 'swagger_fake_view', False):
            return Store.objects.none()

        # Защита от AnonymousUser
        if not self.request.user.is_authenticated:
            return Store.objects.none()

        user = self.request.user

        if user.role == 'admin':
            queryset = Store.objects.all()

        elif user.role == 'partner':
            queryset = Store.objects.filter(
                approval_status=Store.ApprovalStatus.APPROVED,
                is_active=True
            )

        elif user.role == 'store':
            queryset = Store.objects.filter(
                approval_status=Store.ApprovalStatus.APPROVED,
                is_active=True
            )

        else:
            queryset = Store.objects.none()

        # Поиск и фильтрация
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(inn__icontains=search) |
                Q(name__icontains=search) |
                Q(city__name__icontains=search)
            )

        region_id = self.request.query_params.get('region_id')
        if region_id:
            queryset = queryset.filter(region_id=region_id)

        city_id = self.request.query_params.get('city_id')
        if city_id:
            queryset = queryset.filter(city_id=city_id)

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        return queryset.select_related('region', 'city').order_by('-created_at')

    def get_serializer_class(self):
        """Выбор сериализатора в зависимости от action."""
        if self.action == 'list':
            return StoreListSerializer
        elif self.action == 'create':
            return StoreCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return StoreUpdateSerializer
        return StoreSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        """Регистрация нового магазина."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = StoreCreateData(
            name=serializer.validated_data['name'],
            inn=serializer.validated_data['inn'],
            owner_name=serializer.validated_data['owner_name'],
            phone=serializer.validated_data['phone'],
            region_id=serializer.validated_data['region'].id,
            city_id=serializer.validated_data['city'].id,
            address=serializer.validated_data['address'],
            latitude=serializer.validated_data.get('latitude'),
            longitude=serializer.validated_data.get('longitude'),
        )

        store = StoreService.create_store(
            data=data,
            created_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        """Обновление профиля магазина."""
        store = self.get_object()
        user = request.user

        if user.role == 'store':
            current_store = StoreSelectionService.get_current_store(user)
            if not current_store or current_store.id != store.id:
                return Response(
                    {'error': 'Вы можете редактировать только свой магазин'},
                    status=status.HTTP_403_FORBIDDEN
                )

        partial = kwargs.pop('partial', False)
        serializer = self.get_serializer(store, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        data = StoreUpdateData(
            name=serializer.validated_data.get('name'),
            owner_name=serializer.validated_data.get('owner_name'),
            phone=serializer.validated_data.get('phone'),
            region_id=serializer.validated_data.get('region').id if 'region' in serializer.validated_data else None,
            city_id=serializer.validated_data.get('city').id if 'city' in serializer.validated_data else None,
            address=serializer.validated_data.get('address'),
            latitude=serializer.validated_data.get('latitude'),
            longitude=serializer.validated_data.get('longitude'),
        )

        store = StoreService.update_store(
            store=store,
            data=data,
            updated_by=request.user
        )

        output_serializer = StoreSerializer(store)
        return Response(output_serializer.data)

    # =========================================================================
    # ✅ ИСПРАВЛЕНО: FREEZE С @extend_schema И @action
    # =========================================================================

    @extend_schema(
        summary="Заморозить магазин",
        description="Заблокировать магазин (только админ)",
        request=StoreFreezeSerializer,
        responses={
            200: StoreSerializer,
            400: OpenApiResponse(description="Ошибка валидации"),
            403: OpenApiResponse(description="Недостаточно прав"),
        },

    )
    @action(
        detail=True,
        methods=['post'],
        url_path='freeze',
        permission_classes=[IsAuthenticated, IsAdmin]
    )
    def freeze(self, request: Request, pk=None) -> Response:
        """
        Заморозить (заблокировать) магазин.

        Только для администраторов.
        """
        store = self.get_object()

        # Валидация входных данных
        serializer = StoreFreezeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # Вызываем сервис для заморозки
            store = StoreService.freeze_store(
                store=store,
                frozen_by=request.user,
                reason=serializer.validated_data.get('reason', '')
            )

            # Формируем успешный ответ
            output_serializer = StoreSerializer(store)
            return Response(
                {
                    'success': True,
                    'message': f"Магазин '{store.name}' успешно заморожен",
                    'store': output_serializer.data
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            # Обработка ошибок валидации
            return Response(
                {
                    'success': False,
                    'error': str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            # Обработка непредвиденных ошибок
            return Response(
                {
                    'success': False,
                    'error': f'Произошла ошибка при заморозке магазина: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Разморозить магазин",
        description="Разблокировать магазин (только админ)",
        request=StoreUnfreezeSerializer,
        responses={
            200: StoreSerializer,
            400: OpenApiResponse(description="Ошибка валидации"),
            403: OpenApiResponse(description="Недостаточно прав"),
        },
    )
    @action(
        detail=True,
        methods=['post'],
        url_path='unfreeze',
        permission_classes=[IsAuthenticated, IsAdmin]
    )
    def unfreeze(self, request: Request, pk=None) -> Response:
        """
        Разморозить (разблокировать) магазин.

        Только для администраторов.
        """
        store = self.get_object()

        # Валидация входных данных
        serializer = StoreUnfreezeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # Вызываем сервис для разморозки
            store = StoreService.unfreeze_store(
                store=store,
                unfrozen_by=request.user,
                comment=serializer.validated_data.get('comment', '')
            )

            # Формируем успешный ответ
            output_serializer = StoreSerializer(store)
            return Response(
                {
                    'success': True,
                    'message': f"Магазин '{store.name}' успешно разморожен",
                    'store': output_serializer.data
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            # Обработка ошибок валидации
            return Response(
                {
                    'success': False,
                    'error': str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            # Обработка непредвиденных ошибок
            return Response(
                {
                    'success': False,
                    'error': f'Произошла ошибка при разморозке магазина: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Корзина магазина",
        description="""
            Получить корзину магазина (все товары из IN_TRANSIT заказов).

            Корзина = товары из заказов, одобренных админом, но ещё не подтверждённых партнёром.
            Партнёр видит агрегированные товары и может их подтвердить.
            """,
        responses={
            200: OpenApiResponse(description="Корзина магазина"),
            403: OpenApiResponse(description="Доступ запрещён"),
        },
    )
    @action(detail=True, methods=['get'], url_path='basket')
    def basket(self, request: Request, pk=None) -> Response:
        """
        Корзина магазина (товары из IN_TRANSIT заказов).

        GET /api/stores/stores/{id}/basket/
        """
        store = self.get_object()
        user = request.user

        # Магазин не должен видеть корзину
        if user.role == 'store':
            return Response(
                {'error': 'Корзина доступна только для партнёров'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Получаем все IN_TRANSIT заказы
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).prefetch_related('items__product__images').order_by('created_at')

        if not orders.exists():
            return Response({
                'store_id': store.id,
                'store_name': store.name,
                'owner_name': store.owner_name,
                'store_phone': store.phone,
                'is_empty': True,
                'orders_count': 0,
                'items': [],
                'totals': {
                    'piece_count': 0,
                    'weight_total': '0',
                    'total_amount': '0',
                }
            })

        # Агрегируем товары из всех заказов
        items_map = {}

        for order in orders:
            for item in order.items.all():
                product = item.product
                product_id = product.id

                if product_id not in items_map:
                    main_image = None
                    if hasattr(product, 'images'):
                        first_image = product.images.first()
                        if first_image and first_image.image:
                            main_image = first_image.image.url

                    items_map[product_id] = {
                        'product_id': product_id,
                        'product_name': product.name,
                        'product_image': main_image,
                        'is_weight_based': product.is_weight_based,
                        'is_bonus_product': product.is_bonus,
                        'unit': product.unit,
                        'price': item.price,
                        'quantity': Decimal('0'),
                        'total': Decimal('0'),
                        'order_ids': [],
                    }

                items_map[product_id]['quantity'] += item.quantity
                items_map[product_id]['total'] += item.total
                if order.id not in items_map[product_id]['order_ids']:
                    items_map[product_id]['order_ids'].append(order.id)

        # Форматируем результат
        items = []
        piece_count = 0
        weight_total = Decimal('0')
        total_amount = Decimal('0')

        for product_id, data in items_map.items():
            if data['is_weight_based']:
                qty = data['quantity']
                quantity_display = f"{int(qty) if qty == int(qty) else qty} кг"
                weight_total += data['quantity']
            else:
                quantity_display = f"{int(data['quantity'])} шт"
                piece_count += int(data['quantity'])

            total_amount += data['total']

            items.append({
                'product_id': data['product_id'],
                'product_name': data['product_name'],
                'product_image': data['product_image'],
                'is_weight_based': data['is_weight_based'],
                'is_bonus_product': data['is_bonus_product'],
                'unit': data['unit'],
                'quantity': str(data['quantity']),
                'quantity_display': quantity_display,
                'price': str(data['price']),
                'total': str(data['total']),
                'order_ids': data['order_ids'],
            })

        return Response({
            'store_id': store.id,
            'store_name': store.name,
            'owner_name': store.owner_name,
            'store_phone': store.phone,
            'is_empty': False,
            'orders_count': orders.count(),
            'order_ids': list(orders.values_list('id', flat=True)),
            'items': items,
            'totals': {
                'piece_count': piece_count,
                'weight_total': str(int(weight_total) if weight_total == int(weight_total) else weight_total),
                'total_amount': str(total_amount),
            }
        })

    @extend_schema(
        summary="Подтвердить корзину",
        description="""
            Партнёр подтверждает корзину магазина.

            WORKFLOW:
            1. Партнёр может удалить товары (items_to_remove)
            2. Партнёр может изменить количество (items_to_modify)
            3. Партнёр вводит предоплату
            4. Все IN_TRANSIT заказы → ACCEPTED
            5. Товары переносятся в инвентарь магазина
            6. Корзина очищается
            7. Создаётся долг магазина
            """,
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'prepayment_amount': {'type': 'number', 'default': 0},
                    'items_to_remove': {'type': 'array', 'items': {'type': 'integer'}},
                    'items_to_modify': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'product_id': {'type': 'integer'},
                                'new_quantity': {'type': 'number'}
                            }
                        }
                    }
                }
            }
        },
        responses={
            200: OpenApiResponse(description="Корзина подтверждена"),
            400: OpenApiResponse(description="Ошибка валидации"),
            403: OpenApiResponse(description="Только партнёры"),
        },
    )
    @action(detail=True, methods=['post'], url_path='basket/confirm')
    @transaction.atomic
    def confirm_basket(self, request: Request, pk=None) -> Response:
        """
        Партнёр подтверждает корзину магазина.

        POST /api/stores/stores/{id}/basket/confirm/
        """
        store = self.get_object()
        user = request.user

        if user.role != 'partner':
            return Response(
                {'error': 'Только партнёры могут подтверждать корзину'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Параметры
        prepayment_amount = request.data.get('prepayment_amount', 0)
        items_to_remove = request.data.get('items_to_remove', [])
        items_to_modify = request.data.get('items_to_modify', [])

        try:
            prepayment_amount = Decimal(str(prepayment_amount))
        except (ValueError, TypeError):
            return Response(
                {'error': 'Некорректное значение prepayment_amount'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if prepayment_amount < 0:
            return Response(
                {'error': 'Предоплата не может быть отрицательной'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем IN_TRANSIT заказы
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).select_for_update().prefetch_related('items__product')

        if not orders.exists():
            return Response(
                {'error': 'Нет заказов для подтверждения'},
                status=status.HTTP_400_BAD_REQUEST
            )

        removed_info = []
        modified_info = []

        # =====================================================================
        # 1. УДАЛЕНИЕ ТОВАРОВ
        # =====================================================================
        for product_id in items_to_remove:
            deleted_items = StoreOrderItem.objects.filter(
                order__in=orders,
                product_id=product_id
            ).select_related('product')

            for item in deleted_items:
                removed_info.append({
                    'product_id': product_id,
                    'product_name': item.product.name,
                    'quantity': float(item.quantity),
                    'order_id': item.order_id,
                })
                # Возвращаем товар на склад
                item.product.stock_quantity += item.quantity
                item.product.save(update_fields=['stock_quantity'])

            deleted_items.delete()

        # =====================================================================
        # 2. ИЗМЕНЕНИЕ КОЛИЧЕСТВА
        # =====================================================================
        for mod in items_to_modify:
            product_id = mod.get('product_id')
            new_quantity = mod.get('new_quantity')

            if not product_id or new_quantity is None:
                continue

            try:
                new_quantity = Decimal(str(new_quantity))
            except (ValueError, TypeError):
                continue

            items = StoreOrderItem.objects.filter(
                order__in=orders,
                product_id=product_id
            ).select_related('product')

            if not items.exists():
                continue

            current_total = sum(item.quantity for item in items)

            if new_quantity >= current_total:
                continue  # Нельзя увеличивать

            if new_quantity <= 0:
                # Удаляем все позиции
                for item in items:
                    item.product.stock_quantity += item.quantity
                    item.product.save(update_fields=['stock_quantity'])
                    removed_info.append({
                        'product_id': product_id,
                        'product_name': item.product.name,
                        'quantity': float(item.quantity),
                        'order_id': item.order_id,
                    })
                items.delete()
                continue

            # Уменьшаем количество
            difference = current_total - new_quantity
            first_item = items.first()
            product = first_item.product

            if first_item.quantity >= difference:
                old_qty = first_item.quantity
                first_item.quantity -= difference
                first_item.total = first_item.quantity * first_item.price
                first_item.save(update_fields=['quantity', 'total'])

                product.stock_quantity += difference
                product.save(update_fields=['stock_quantity'])

                modified_info.append({
                    'product_id': product_id,
                    'product_name': product.name,
                    'old_quantity': float(old_qty),
                    'new_quantity': float(first_item.quantity),
                    'order_id': first_item.order_id,
                })

        # =====================================================================
        # 3. ПЕРЕСЧЁТ СУММ ЗАКАЗОВ
        # =====================================================================
        for order in orders:
            order.refresh_from_db()
            new_total = sum(item.total for item in order.items.all())
            order.total_amount = new_total
            order.save(update_fields=['total_amount'])

        # =====================================================================
        # 4. РАСЧЁТ ОБЩЕЙ СУММЫ И ДОЛГА
        # =====================================================================
        total_amount = sum(order.total_amount for order in orders)

        if prepayment_amount > total_amount:
            return Response(
                {
                    'error': f'Предоплата ({prepayment_amount} сом) превышает '
                             f'сумму заказов ({total_amount} сом)'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        total_debt = total_amount - prepayment_amount

        # =====================================================================
        # 5. ПОДТВЕРЖДЕНИЕ ЗАКАЗОВ И ПЕРЕНОС В ИНВЕНТАРЬ
        # =====================================================================
        confirmed_orders = []

        for order in orders:
            if total_amount > 0:
                order_prepayment = (order.total_amount / total_amount) * prepayment_amount
            else:
                order_prepayment = Decimal('0')

            order_debt = order.total_amount - order_prepayment

            old_status = order.status
            order.status = StoreOrderStatus.ACCEPTED
            order.partner = user
            order.confirmed_by = user
            order.confirmed_at = timezone.now()
            order.prepayment_amount = order_prepayment
            order.debt_amount = order_debt

            order.save(update_fields=[
                'status', 'partner', 'confirmed_by', 'confirmed_at',
                'prepayment_amount', 'debt_amount'
            ])

            # ✅ КРИТИЧНО: Переносим товары в инвентарь ЗДЕСЬ
            for item in order.items.all():
                StoreInventoryService.add_to_inventory(
                    store=store,
                    product=item.product,
                    quantity=item.quantity
                )

            # История
            OrderHistory.objects.create(
                order_type=OrderType.STORE,
                order_id=order.id,
                old_status=old_status,
                new_status=StoreOrderStatus.ACCEPTED,
                changed_by=user,
                comment=(
                    f'Заказ подтверждён партнёром. '
                    f'Сумма: {order.total_amount} сом. '
                    f'Предоплата: {order_prepayment} сом. '
                    f'Долг: {order_debt} сом.'
                )
            )

            confirmed_orders.append({
                'order_id': order.id,
                'total_amount': float(order.total_amount),
                'prepayment': float(order_prepayment),
                'debt': float(order_debt),
            })

        # =====================================================================
        # 6. ОБНОВЛЕНИЕ ДОЛГА МАГАЗИНА
        # =====================================================================
        Store.objects.filter(pk=store.pk).update(debt=F('debt') + total_debt)
        store.refresh_from_db()

        return Response({
            'success': True,
            'message': f'Корзина подтверждена. Заказов: {len(confirmed_orders)}',
            'confirmed_orders': confirmed_orders,
            'totals': {
                'total_amount': float(total_amount),
                'prepayment': float(prepayment_amount),
                'debt_created': float(total_debt),
            },
            'store_debt': float(store.debt),
            'removed_items': removed_info,
            'modified_items': modified_info,
        })

    @extend_schema(
        summary="Инвентарь магазина",
        description="""
            Получить инвентарь магазина (товары из ACCEPTED заказов).

            Инвентарь = история всех доставленных товаров.
            Используется для выбора бракованных товаров.

            ВАЖНО: Магазин не видит инвентарь, пока есть заказы в статусе IN_TRANSIT.
            """,
        responses={
            200: StoreInventoryListSerializer(many=True),
            403: OpenApiResponse(description="Инвентарь недоступен"),
        },

    )
    @action(detail=True, methods=['get'], url_path='inventory')
    def inventory(self, request: Request, pk=None) -> Response:
        """
        Инвентарь магазина (товары из ACCEPTED заказов).

        GET /api/stores/stores/{id}/inventory/
        """
        store = self.get_object()
        user = request.user

        # Магазин не видит инвентарь пока есть IN_TRANSIT заказы
        if user.role == 'store':
            has_in_transit = StoreOrder.objects.filter(
                store=store,
                status=StoreOrderStatus.IN_TRANSIT
            ).exists()

            if has_in_transit:
                return Response(
                    {
                        'error': 'Инвентарь недоступен',
                        'message': 'Дождитесь подтверждения заказов партнёром'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        inventory = StoreInventoryService.get_inventory(store)

        page = self.paginate_queryset(inventory)
        if page is not None:
            serializer = StoreInventoryListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StoreInventoryListSerializer(inventory, many=True)
        return Response(serializer.data)

    # =========================================================================
    # ОТМЕТКА БРАКА ИЗ ИНВЕНТАРЯ
    # =========================================================================

    @extend_schema(
        summary="Отметить брак",
        description="""
            Партнёр отмечает бракованные товары из инвентаря.

            Брак сразу одобряется и долг магазина уменьшается.
            """,
        request={
            'application/json': {
                'type': 'object',
                'required': ['product_id', 'quantity', 'reason'],
                'properties': {
                    'product_id': {'type': 'integer', 'description': 'ID товара из инвентаря'},
                    'quantity': {'type': 'number', 'description': 'Количество брака'},
                    'reason': {'type': 'string', 'description': 'Причина брака'}
                }
            }
        },
        responses={
            200: OpenApiResponse(description="Брак зафиксирован"),
            400: OpenApiResponse(description="Ошибка валидации"),
            403: OpenApiResponse(description="Только партнёры"),
            404: OpenApiResponse(description="Товар не найден"),
        },
    )
    @action(detail=True, methods=['post'], url_path='inventory/report-defect')
    @transaction.atomic
    def report_defect(self, request: Request, pk=None) -> Response:
        """
        Партнёр отмечает бракованные товары из инвентаря.

        POST /api/stores/stores/{id}/inventory/report-defect/
        """
        store = self.get_object()
        user = request.user

        if user.role != 'partner':
            return Response(
                {'error': 'Только партнёры могут отмечать брак'},
                status=status.HTTP_403_FORBIDDEN
            )

        product_id = request.data.get('product_id')
        quantity = request.data.get('quantity')
        reason = request.data.get('reason', '').strip()

        if not product_id:
            return Response(
                {'error': 'Укажите product_id'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not quantity:
            return Response(
                {'error': 'Укажите quantity'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not reason:
            return Response(
                {'error': 'Укажите причину брака'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            quantity = Decimal(str(quantity))
        except (ValueError, TypeError):
            return Response(
                {'error': 'Некорректное значение quantity'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if quantity <= 0:
            return Response(
                {'error': 'Количество должно быть больше 0'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Проверка наличия товара в инвентаре
        try:
            inventory_item = StoreInventory.objects.select_related('product').get(
                store=store,
                product_id=product_id
            )
        except StoreInventory.DoesNotExist:
            return Response(
                {'error': 'Товар не найден в инвентаре магазина'},
                status=status.HTTP_404_NOT_FOUND
            )

        product = inventory_item.product

        if quantity > inventory_item.quantity:
            return Response(
                {'error': f'Недостаточно товара. Доступно: {inventory_item.quantity}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        price = product.final_price
        defect_amount = quantity * price

        # Находим последний ACCEPTED заказ
        last_order = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED
        ).order_by('-confirmed_at').first()

        if not last_order:
            return Response(
                {'error': 'Нет подтверждённых заказов для привязки брака'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Создаём запись о браке
        defect = DefectiveProduct.objects.create(
            order=last_order,
            product=product,
            quantity=quantity,
            price=price,
            total_amount=defect_amount,
            reason=reason,
            status=DefectiveProduct.DefectStatus.APPROVED,
            reported_by=user,
            reviewed_by=user,
        )

        # Уменьшаем инвентарь
        inventory_item.quantity -= quantity
        if inventory_item.quantity <= 0:
            inventory_item.delete()
        else:
            inventory_item.save(update_fields=['quantity', 'last_updated'])

        # Уменьшаем долг магазина
        Store.objects.filter(pk=store.pk).update(debt=F('debt') - defect_amount)
        store.refresh_from_db()

        return Response({
            'success': True,
            'message': f'Брак зафиксирован. Долг уменьшен на {defect_amount} сом.',
            'defect': {
                'id': defect.id,
                'product_id': product_id,
                'product_name': product.name,
                'quantity': float(quantity),
                'price': float(price),
                'total_amount': float(defect_amount),
                'reason': reason,
            },
            'store_debt': float(store.debt),
        })

    @action(
        detail=True,
        methods=['post'],
        url_path='pay-debt',
        permission_classes=[IsAuthenticated]
    )
    def pay_store_debt(self, request: Request, pk=None) -> Response:
        """
        Погашение долга магазина (ТЗ v2.0).

        POST /api/stores/{store_id}/pay-debt/

        Body: {
            "amount": 50000000,
            "comment": "Частичное погашение долга"
        }

        ВАЖНО:
        - Уменьшает ОБЩИЙ долг магазина (store.debt)
        - НЕ привязано к конкретному заказу
        - Может погашать:
          * Магазин (себе)
          * Партнёр (за магазин)
          * Админ (корректировка)

        Результат:
        - Долг магазина уменьшается
        - Погашенный долг идёт в доход партнёра
        - Создаётся запись DebtPayment
        """
        from decimal import Decimal
        from django.db.models import F
        from rest_framework import status
        from orders.models import DebtPayment, StoreOrder, StoreOrderStatus
        from stores.models import Store

        store = self.get_object()

        # =========================================================================
        # ВАЛИДАЦИЯ ДАННЫХ
        # =========================================================================

        amount = request.data.get('amount')
        comment = request.data.get('comment', '')

        if not amount:
            return Response(
                {'error': 'Укажите amount'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            amount = Decimal(str(amount))
        except (ValueError, TypeError):
            return Response(
                {'error': 'Некорректное значение amount'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount <= 0:
            return Response(
                {'error': 'Сумма должна быть больше 0'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount > store.debt:
            return Response(
                {
                    'error': f'Сумма погашения ({amount} сом) превышает '
                             f'долг магазина ({store.debt} сом)'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================================
        # ПОИСК ЗАКАЗА ДЛЯ СВЯЗИ
        # =========================================================================

        # Находим последний подтверждённый заказ для технической связи
        # (DebtPayment привязан к order по структуре БД)
        last_order = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED
        ).order_by('-confirmed_at').first()

        if not last_order:
            return Response(
                {
                    'error': 'У магазина нет подтверждённых заказов. '
                             'Погашение долга возможно только после подтверждения заказов.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================================
        # ОПРЕДЕЛЕНИЕ УЧАСТНИКОВ ПЛАТЕЖА
        # =========================================================================

        # Кто платит
        paid_by = request.user

        # Кто получает
        if request.user.role == 'partner':
            # Партнёр платит за магазин - сам себе и получает
            received_by = request.user
        elif request.user.role == 'admin':
            # Админ корректирует - получает партнёр заказа
            received_by = last_order.partner if last_order.partner else None
        elif request.user.role == 'store':
            # Магазин платит - получает партнёр заказа
            received_by = last_order.partner if last_order.partner else None
        else:
            received_by = None

        # =========================================================================
        # ОБНОВЛЕНИЕ ДОЛГА МАГАЗИНА
        # =========================================================================

        # ✅ ИСПРАВЛЕНО: Используем update() чтобы избежать ValidationError с F()
        Store.objects.filter(pk=store.pk).update(
            debt=F('debt') - amount,
            total_paid=F('total_paid') + amount
        )

        # Перезагружаем магазин чтобы получить актуальные значения
        store.refresh_from_db()

        # =========================================================================
        # СОЗДАНИЕ ЗАПИСИ О ПОГАШЕНИИ
        # =========================================================================

        payment = DebtPayment.objects.create(
            order=last_order,  # Связываем с последним заказом (технически)
            amount=amount,
            paid_by=paid_by,
            received_by=received_by,
            comment=comment.strip() if comment else ''
        )

        # =========================================================================
        # ОТВЕТ
        # =========================================================================

        from orders.serializers import DebtPaymentSerializer
        payment_serializer = DebtPaymentSerializer(payment)

        return Response({
            'success': True,
            'message': 'Долг успешно погашен',
            'payment': payment_serializer.data,
            'store_debt_before': float(store.debt + amount),
            'payment_amount': float(amount),
            'store_debt_after': float(store.debt),
            'store_total_paid': float(store.total_paid)
        }, status=status.HTTP_201_CREATED)

    # ============================================================================
    # ИМПОРТЫ КОТОРЫЕ НУЖНО ДОБАВИТЬ В НАЧАЛО ФАЙЛА stores/views.py
    # ============================================================================

    # from decimal import Decimal
    # from django.db.models import F
    # from rest_framework import status
    # from rest_framework.permissions import IsAuthenticated
    # from orders.models import DebtPayment, StoreOrder, StoreOrderStatus
    # from stores.models import Store


# =============================================================================
# ВЫБОР МАГАЗИНА
# =============================================================================

class SelectStoreView(APIView):
    """
    Выбрать магазин для работы (только для role='store').

    ✅ ИСПРАВЛЕНО: Поддерживает store_id из body И query params.
    """

    permission_classes = [IsAuthenticated, IsStore]

    @extend_schema(
        summary="Выбрать магазин",
        description="Выбрать магазин для работы. Store_id можно передать в body или query параметре.",
        request=StoreSelectionCreateSerializer,
        responses={
            200: StoreSelectionSerializer,
            400: OpenApiResponse(description="Магазин не найден или заблокирован"),
        },
        parameters=[
            OpenApiParameter(
                name='store_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID магазина (альтернатива передаче в body)',
                required=False
            )
        ],
    )
    def post(self, request: Request) -> Response:
        """Выбрать магазин."""
        # ✅ ИСПРАВЛЕНО: Поддержка store_id из query params ИЛИ body
        store_id = request.query_params.get('store_id') or request.data.get('store_id')

        if not store_id:
            return Response(
                {'error': 'store_id обязателен (в body или query params)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Валидация
        serializer = StoreSelectionCreateSerializer(data={'store_id': store_id})
        serializer.is_valid(raise_exception=True)

        selection = StoreSelectionService.select_store(
            user=request.user,
            store_id=serializer.validated_data['store_id']
        )

        output_serializer = StoreSelectionSerializer(selection)
        return Response(output_serializer.data, status=status.HTTP_200_OK)


class DeselectStoreView(APIView):
    """
    Отменить выбор текущего магазина (только для role='store').
    """

    permission_classes = [IsAuthenticated, IsStore]

    @extend_schema(
        summary="Отменить выбор магазина",
        description="Отменить выбор текущего магазина",
        request=None,
        responses={
            200: OpenApiResponse(description="Выбор отменён"),
            404: OpenApiResponse(description="Активный магазин не найден"),
        },

    )
    def post(self, request: Request) -> Response:
        """Отменить выбор магазина."""
        deselected = StoreSelectionService.deselect_store(request.user)

        if deselected:
            return Response(
                {'message': 'Выбор магазина отменён'},
                status=status.HTTP_200_OK
            )

        return Response(
            {'message': 'Активный магазин не найден'},
            status=status.HTTP_404_NOT_FOUND
        )


# =============================================================================
# ФУНКЦИОНАЛЬНЫЕ VIEWS
# =============================================================================

@extend_schema(
    summary="Текущий магазин",
    description="Получить профиль текущего выбранного магазина",
    responses={
        200: StoreSerializer,
        404: OpenApiResponse(description="Магазин не выбран"),
    },
    tags=['Магазины']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated, IsStore])
def get_current_store_profile(request: Request) -> Response:
    """
    Профиль текущего магазина пользователя.

    GET /api/stores/profile/
    """
    store = StoreSelectionService.get_current_store(request.user)

    if not store:
        return Response(
            {'error': 'Магазин не выбран'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = StoreSerializer(store)
    return Response(serializer.data)


@extend_schema(
    summary="Пользователи в магазине",
    description="Получить список пользователей, работающих в магазине",
    responses={200: {'type': 'array', 'items': {'type': 'object'}}},
    tags=['Магазины']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_users_in_store(request: Request, pk: int) -> Response:
    """
    Список пользователей, работающих в магазине.

    GET /api/stores/{id}/users/
    """
    try:
        store = Store.objects.get(pk=pk)
    except Store.DoesNotExist:
        return Response(
            {'error': 'Магазин не найден'},
            status=status.HTTP_404_NOT_FOUND
        )

    users = StoreSelectionService.get_users_in_store(store)

    users_data = [
        {
            'id': user.id,
            'full_name': user.get_full_name(),
            'email': user.email,
            'phone': user.phone
        }
        for user in users
    ]

    return Response({
        'store_id': store.id,
        'store_name': store.name,
        'users_count': len(users_data),
        'users': users_data
    })