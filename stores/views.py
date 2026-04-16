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
from django.db.models import QuerySet, Q, F, Sum, Count  # ✅ Добавлен Q, Sum, Count
from django.db.models.functions import Coalesce
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

from users.throttles import StoreSelectionThrottle
from .permissions import IsPartner, IsStore, IsStoreOwner, CanAccessStore

from .models import (
    Region,
    City,
    Store,
    StoreSelection,
    StoreInventory, PartnerInventory,
)
from products.models import Product
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
    StoreUnfreezeSerializer, ReserveQuantitySerializer, PartnerInventorySerializer, ReleaseQuantitySerializer,
    PartnerInventoryListSerializer,
)
from .services import (
    StoreService,
    StoreSelectionService,
    StoreInventoryService,
    GeographyService,
    BonusCalculationService,  # ✅ НОВОЕ v2.0
    StoreCreateData,
    StoreUpdateData,
    StoreSearchFilters, PartnerInventoryService,
)
from .permissions import IsAdmin, IsStore, IsAdminOrReadOnly
from orders.models import (
    StoreOrder,
    StoreOrderStatus,
    StoreOrderItem,
    OrderHistory,
    OrderType,
    DefectiveProduct,  # ✅ Статус внутри: DefectiveProduct.DefectStatus
    ReturnedItem,  # ✅ Для учёта возвращённых товаров
)
# =============================================================================
# PAGINATION
# =============================================================================

class StandardPagination(PageNumberPagination):
    """Стандартная пагинация."""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100


def _build_inventory_items(inventory_qs, use_available_quantity=False):
    """
    Построить список items и totals из queryset инвентаря.

    Используется в basket, partner-inventory, store-inventory.
    Queryset должен иметь select_related('product') и prefetch_related('product__images').

    use_available_quantity: если True, показывать available_quantity вместо quantity
    (для PartnerInventory чтобы учесть зарезервированные товары).
    """
    items = []
    piece_count = 0
    weight_total = Decimal('0')
    total_amount = Decimal('0')

    for inv in inventory_qs:
        product = inv.product

        main_image = None
        if hasattr(product, 'images'):
            # Используем prefetch-кэш (.all()) вместо .first() чтобы избежать N+1
            cached_images = list(product.images.all())
            if cached_images and cached_images[0].image:
                main_image = cached_images[0].image.url

        # Для PartnerInventory показываем available_quantity (доступное, без резерва)
        display_qty = inv.available_quantity if use_available_quantity and hasattr(inv, 'available_quantity') else inv.quantity

        price = product.final_price
        total = display_qty * price

        if product.is_weight_based:
            qty = display_qty
            quantity_display = f"{int(qty) if qty == int(qty) else qty} кг"
            weight_total += display_qty
        else:
            quantity_display = f"{int(display_qty)} шт"
            piece_count += int(display_qty)

        total_amount += total

        item = {
            'product_id': product.id,
            'product_name': product.name,
            'product_image': main_image,
            'is_weight_based': product.is_weight_based,
            'is_bonus_product': product.is_bonus,
            'unit': product.unit,
            'quantity': str(display_qty),
            'quantity_display': quantity_display,
            'price': str(price),
            'total': str(total),
        }

        # Дополнительные поля для PartnerInventory
        if hasattr(inv, 'is_bonus'):
            item['is_bonus'] = inv.is_bonus
        if use_available_quantity and hasattr(inv, 'reserved_quantity'):
            item['reserved_quantity'] = str(inv.reserved_quantity)
            item['total_quantity'] = str(inv.quantity)

        # Доп цены (используем prefetch-кэш чтобы избежать N+1)
        if hasattr(product, '_prefetched_objects_cache') and 'additional_prices' in product._prefetched_objects_cache:
            item['additional_prices'] = [
                {'id': ap.id, 'name': ap.name, 'price': str(ap.price), 'is_active': ap.is_active}
                for ap in product.additional_prices.all()
                if ap.is_active
            ]

        items.append(item)

    totals = {
        'piece_count': piece_count,
        'weight_total': str(int(weight_total) if weight_total == int(weight_total) else weight_total),
        'total_amount': str(total_amount),
    }

    return items, totals


def _paginate_items(items, request, page_size=30):
    """Пагинировать список items вручную."""
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', page_size))
    page_size = min(page_size, 100)

    total_count = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    paginated_items = items[start:end]

    total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 1

    return paginated_items, {
        'count': total_count,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
    }


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

    queryset = Region.objects.prefetch_related('cities', 'stores')
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

    queryset = City.objects.select_related('region').prefetch_related('stores')
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

    def get_permissions(self):
        """
        Определить permissions в зависимости от действия.
        
        v3.0:
        - create: IsAuthenticated
        - update/destroy: IsStoreOwner
        - retrieve/list: CanAccessStore
        """
        if self.action == 'create':
            return [IsAuthenticated()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsStoreOwner()]
        elif self.action in ['retrieve', 'list']:
            return [IsAuthenticated(), CanAccessStore()]
        return [IsAuthenticated()]

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

        elif user.role == 'store':
            # 🔴 v3.0: Пользователь видит только СВОИ магазины
            queryset = Store.objects.filter(owner=user)

        elif user.role == 'partner':
            # Партнер видит все активные магазины
            queryset = Store.objects.filter(is_active=True)

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

        # =====================================================================
        # v3.0: Фильтр по типу заказа (предзаказ / ручной сбор)
        # 
        # WORKFLOW:
        # 1. Магазин создаёт заказ → status=PENDING
        # 2. Партнёр подтверждает через accept-preorder → status=IN_TRANSIT (попадает в корзину)
        # 3. Партнёр подтверждает корзину → status=ACCEPTED, товары → инвентарь магазина
        #
        # ФИЛЬТРЫ:
        # - preorder: Магазины с заказами в статусе IN_TRANSIT (в корзине партнёра)
        # - manual: Магазины БЕЗ активных заказов (доступны для ручного сбора)
        # =====================================================================
        order_type_filter = self.request.query_params.get('order_type')
        if order_type_filter == 'preorder':
            # Магазины с предзаказами в статусе IN_TRANSIT
            # (партнёр принял через accept-preorder, товары в корзине)
            from orders.models import StoreOrder, StoreOrderStatus
            store_ids = StoreOrder.objects.filter(
                status=StoreOrderStatus.IN_TRANSIT
            ).values_list('store_id', flat=True).distinct()
            queryset = queryset.filter(id__in=store_ids)
        elif order_type_filter == 'manual':
            # Магазины БЕЗ активных заказов (нет PENDING и IN_TRANSIT)
            # Эти магазины доступны для ручного сбора партнёром
            from orders.models import StoreOrder, StoreOrderStatus
            stores_with_active_orders = StoreOrder.objects.filter(
                status__in=[StoreOrderStatus.PENDING, StoreOrderStatus.IN_TRANSIT]
            ).values_list('store_id', flat=True).distinct()
            queryset = queryset.exclude(id__in=stores_with_active_orders)

        # Фильтр по долгу (debt__gt=0.0)
        debt_gt = self.request.query_params.get('debt__gt')
        if debt_gt is not None:
            try:
                queryset = queryset.filter(debt__gt=Decimal(debt_gt))
            except (ValueError, ArithmeticError):
                from rest_framework.exceptions import ValidationError
                raise ValidationError({'debt__gt': 'Некорректное числовое значение'})

        # Аннотации COUNT — только для retrieve (StoreSerializer их использует)
        # Для list (StoreListSerializer) не нужны — экономим 4 подзапроса
        if self.action == 'retrieve':
            queryset = queryset.annotate(
                total_orders_count=Count('orders', distinct=True),
                accepted_orders_count=Count('orders', filter=Q(orders__status='accepted'), distinct=True),
                inventory_items_count=Count('inventory', distinct=True),
                users_count=Count('selections', filter=Q(selections__is_current=True), distinct=True),
            )
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
        """
        Создание нового магазина.

        Партнёр ДОЛЖЕН указать owner_id (пользователь с role='store').
        Пользователь role='store' становится owner автоматически.
        """
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        # Определяем owner в зависимости от роли
        if request.user.role == 'partner':
            # Партнёр ОБЯЗАН указать owner_id.
            # validate_owner_id уже проверил существование и роль,
            # и сохранил объект в context['_validated_owner'] — берём оттуда.
            owner_id = serializer.validated_data.get('owner_id')
            if not owner_id:
                return Response(
                    {'error': 'Партнёр должен указать owner_id (пользователь с ролью store)'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Берём из context — без лишнего запроса к БД
            owner = serializer.context.get('_validated_owner')
            if not owner:
                # Fallback на случай если context не прокинулся
                from users.models import User
                try:
                    owner = User.objects.get(id=owner_id, role='store')
                except User.DoesNotExist:
                    return Response(
                        {'error': 'Пользователь не найден или не имеет роль store'},
                        status=status.HTTP_404_NOT_FOUND
                    )
        else:
            # Для role='store' — owner = сам пользователь
            owner = request.user

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
            created_by=request.user,
            owner=owner
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

        paginated_items, pagination = _paginate_items(items, request)

        return Response({
            'store_id': store.id,
            'store_name': store.name,
            'owner_name': store.owner_name,
            'store_phone': store.phone,
            'is_empty': False,
            'orders_count': orders.count(),
            'order_ids': list(orders.values_list('id', flat=True)),
            'items': paginated_items,
            'pagination': pagination,
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
    # ============================================================================
    # ПАТЧ ДЛЯ apps/stores/views.py - ЗАМЕНА МЕТОДА confirm_basket
    # ============================================================================
    #
    # ЗАМЕНИТЬ метод confirm_basket на ДВА МЕТОДА:
    # 1. remove_from_basket - удаление/изменение товаров
    # 2. confirm_basket - подтверждение с предоплатой
    #
    # НАЙТИ И УДАЛИТЬ: строки 649-924 (весь метод confirm_basket)
    # ВСТАВИТЬ: код ниже
    # ============================================================================

    @extend_schema(
        summary="Удалить/изменить товары в корзине",
        description="""
                Партнёр удаляет или изменяет количество товаров в корзине магазина.

                Работает с заказами в статусе IN_TRANSIT.
                НЕ меняет статус заказов, НЕ переносит в инвентарь, НЕ создает долг.

                WORKFLOW:
                1. Партнёр просматривает корзину (GET /basket/)
                2. Партнёр видит товары, которые ему не нужны
                3. Партнёр удаляет ненужные товары или уменьшает количество
                4. Товары возвращаются на склад
                5. Суммы заказов пересчитываются
                6. Возвращается обновлённая корзина

                После этого партнёр вызывает confirm (подтверждение с предоплатой).
                """,
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'items_to_remove': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'ID товаров для полного удаления из корзины',
                        'example': [1, 2, 3]
                    },
                    'items_to_modify': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'product_id': {'type': 'integer'},
                                'new_quantity': {'type': 'number'}
                            }
                        },
                        'description': 'Товары с новым количеством (только уменьшение)',
                        'example': [
                            {'product_id': 4, 'new_quantity': 50},
                            {'product_id': 5, 'new_quantity': 2.5}
                        ]
                    }
                }
            }
        },
        responses={
            200: OpenApiResponse(description="Корзина обновлена"),
            400: OpenApiResponse(description="Ошибка валидации"),
            403: OpenApiResponse(description="Только партнёры"),
        },
    )
    @extend_schema(
        summary="Удалить/изменить товары в корзине",
        description="""
                Партнёр удаляет товары или уменьшает их количество в корзине магазина.

                ЛОГИКА:
                - items_to_remove: полностью удаляет товары по ID
                - items_to_modify: удаляет УКАЗАННОЕ количество из корзины

                ПРИМЕРЫ:
                1. Полное удаление:
                   {"items_to_remove": [1, 2, 3]} - удалит товары 1, 2, 3 полностью

                2. Частичное удаление:
                   Было: Курица 5 кг
                   Запрос: {"items_to_modify": [{"product_id": 10, "quantity_to_remove": 2}]}
                   Стало: Курица 3 кг

                WORKFLOW:
                1. Партнёр просматривает корзину (GET /basket/)
                2. Партнёр видит ненужные товары
                3. Партнёр удаляет товары или уменьшает количество
                4. Товары возвращаются на склад
                5. Возвращается обновлённая корзина
                """,
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'items_to_remove': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'ID товаров для полного удаления из корзины',
                        'example': [1, 2, 3]
                    },
                    'items_to_modify': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'product_id': {
                                    'type': 'integer',
                                    'description': 'ID товара'
                                },
                                'quantity_to_remove': {
                                    'type': 'number',
                                    'description': 'Сколько штук/кг удалить (НЕ финальное количество!)'
                                }
                            }
                        },
                        'description': 'Товары с количеством для удаления',
                        'example': [
                            {'product_id': 4, 'quantity_to_remove': 50},
                            {'product_id': 5, 'quantity_to_remove': 2.5}
                        ]
                    }
                }
            }
        },
        responses={
            200: OpenApiResponse(description="Корзина обновлена"),
            400: OpenApiResponse(description="Ошибка валидации"),
            403: OpenApiResponse(description="Только партнёры"),
        },
    )
    @action(detail=True, methods=['post'], url_path='basket/remove')
    @transaction.atomic
    def remove_from_basket(self, request: Request, pk=None) -> Response:
        """
        Партнёр удаляет/изменяет товары из корзины магазина.

        POST /api/stores/stores/{id}/basket/remove/
        """
        store = self.get_object()
        user = request.user

        if user.role != 'partner':
            return Response(
                {'error': 'Только партнёры могут редактировать корзину'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Параметры
        items_to_remove = request.data.get('items_to_remove', [])
        items_to_modify = request.data.get('items_to_modify', [])

        if not items_to_remove and not items_to_modify:
            return Response(
                {'error': 'Не указаны товары для удаления или изменения'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем IN_TRANSIT заказы.
        # order_by('id') обязателен: без детерминированного порядка
        # select_for_update может вызвать deadlock при параллельных запросах.
        orders = list(StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).order_by('id').select_for_update().prefetch_related('items__product'))

        if not orders:
            return Response(
                {'error': 'Нет заказов в корзине'},
                status=status.HTTP_400_BAD_REQUEST
            )

        removed_info = []
        modified_info = []

        # =====================================================================
        # 1. ПОЛНОЕ УДАЛЕНИЕ ТОВАРОВ (items_to_remove)
        # =====================================================================
        for product_id in items_to_remove:
            deleted_items = StoreOrderItem.objects.filter(
                order__in=orders,
                product_id=product_id
            ).select_related('product').select_for_update()

            for item in deleted_items:
                # ✅ Создаём запись о возврате
                ReturnedItem.objects.create(
                    order=item.order,
                    product=item.product,
                    quantity=item.quantity,
                    weight=item.weight if hasattr(item, 'weight') and item.weight else None,
                    price_at_return=item.price,
                    reason='Удалено из корзины партнёром',
                    returned_by=user,
                )
                
                removed_info.append({
                    'product_id': product_id,
                    'product_name': item.product.name,
                    'quantity_removed': float(item.quantity),
                    'order_id': item.order_id,
                })
                # Освобождаем резерв в PartnerInventory
                PartnerInventoryService.release_reserved(
                    partner=user,
                    product=item.product,
                    quantity=item.quantity,
                    is_bonus=item.is_bonus,
                )
                # Возвращаем товар на склад атомарно
                Product.objects.filter(pk=item.product_id).update(
                    stock_quantity=F('stock_quantity') + item.quantity
                )

            deleted_items.delete()

        # =====================================================================
        # 2. ЧАСТИЧНОЕ УДАЛЕНИЕ (items_to_modify)
        # ЛОГИКА: Удаляем УКАЗАННОЕ количество, не уменьшаем ДО
        # =====================================================================
        for mod in items_to_modify:
            product_id = mod.get('product_id')
            quantity_to_remove = mod.get('quantity_to_remove')

            if not product_id or quantity_to_remove is None:
                continue

            try:
                quantity_to_remove = Decimal(str(quantity_to_remove))
            except (ValueError, TypeError):
                continue

            if quantity_to_remove <= 0:
                continue  # Нельзя удалить 0 или отрицательное количество

            # Находим все позиции с этим товаром
            items = StoreOrderItem.objects.filter(
                order__in=orders,
                product_id=product_id
            ).select_related('product').order_by('id').select_for_update()

            if not items.exists():
                continue

            # Считаем текущее общее количество
            current_total = sum(item.quantity for item in items)

            # ✅ КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: проверяем, что удаляем не больше чем есть
            if quantity_to_remove > current_total:
                # Нельзя удалить больше чем есть - удаляем всё
                quantity_to_remove = current_total

            # Удаляем указанное количество
            remaining_to_remove = quantity_to_remove

            for item in items:
                if remaining_to_remove <= 0:
                    break

                product = item.product

                if item.quantity <= remaining_to_remove:
                    # Удаляем позицию полностью
                    removed_qty = item.quantity
                    remaining_to_remove -= removed_qty

                    # ✅ Создаём запись о возврате
                    ReturnedItem.objects.create(
                        order=item.order,
                        product=product,
                        quantity=removed_qty,
                        weight=item.weight if hasattr(item, 'weight') and item.weight else None,
                        price_at_return=item.price,
                        reason='Частично удалено из корзины партнёром',
                        returned_by=user,
                    )

                    # Освобождаем резерв в PartnerInventory
                    PartnerInventoryService.release_reserved(
                        partner=user,
                        product=product,
                        quantity=removed_qty,
                        is_bonus=item.is_bonus,
                    )

                    # Возвращаем на склад атомарно
                    Product.objects.filter(pk=product.pk).update(
                        stock_quantity=F('stock_quantity') + removed_qty
                    )

                    removed_info.append({
                        'product_id': product_id,
                        'product_name': product.name,
                        'quantity_removed': float(removed_qty),
                        'order_id': item.order_id,
                    })

                    item.delete()
                else:
                    # Уменьшаем позицию частично
                    old_qty = item.quantity
                    removed_qty = remaining_to_remove
                    item.quantity -= remaining_to_remove
                    item.total = item.quantity * item.price
                    item.save(update_fields=['quantity', 'total'])

                    # ✅ Создаём запись о возврате для удалённой части
                    # Для весовых товаров: пропорционально распределяем вес
                    partial_weight = None
                    if product.is_weight_based and item.weight:
                        partial_weight = (removed_qty / old_qty) * item.weight

                    ReturnedItem.objects.create(
                        order=item.order,
                        product=product,
                        quantity=removed_qty,
                        weight=partial_weight,
                        price_at_return=item.price,
                        reason='Частично удалено из корзины партнёром',
                        returned_by=user,
                    )

                    # Освобождаем резерв в PartnerInventory
                    PartnerInventoryService.release_reserved(
                        partner=user,
                        product=product,
                        quantity=removed_qty,
                        is_bonus=item.is_bonus,
                    )

                    # Возвращаем на склад атомарно
                    Product.objects.filter(pk=product.pk).update(
                        stock_quantity=F('stock_quantity') + remaining_to_remove
                    )

                    modified_info.append({
                        'product_id': product_id,
                        'product_name': product.name,
                        'quantity_before': float(old_qty),
                        'quantity_removed': float(removed_qty),
                        'quantity_after': float(item.quantity),
                        'order_id': item.order_id,
                    })

                    remaining_to_remove = Decimal('0')

        # =====================================================================
        # 3. ПЕРЕСЧЁТ СУММ ЗАКАЗОВ (один агрегационный запрос + bulk_update)
        # =====================================================================
        # Один запрос вместо N*2
        order_totals_map = {
            row['order_id']: row['total']
            for row in StoreOrderItem.objects.filter(order__in=orders)
            .values('order_id')
            .annotate(total=Coalesce(Sum('total'), Decimal('0')))
        }

        orders_to_update = list(orders)
        for order in orders_to_update:
            order.total_amount = order_totals_map.get(order.id, Decimal('0'))

        StoreOrder.objects.bulk_update(orders_to_update, ['total_amount'])

        # =====================================================================
        # 4. ВОЗВРАЩАЕМ ОБНОВЛЁННУЮ КОРЗИНУ
        # =====================================================================
        # Перезагружаем заказы после всех изменений
        orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).prefetch_related('items__product__images')

        # Агрегируем товары
        items_map = {}

        for order in orders:
            for item in order.items.all():
                product = item.product
                product_id = product.id

                if product_id not in items_map:
                    main_image = None
                    if hasattr(product, 'images'):
                        # Используем prefetch-кэш (.all()) вместо .first() чтобы избежать N+1
                        cached_images = list(product.images.all())
                        if cached_images and cached_images[0].image:
                            main_image = cached_images[0].image.url

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

        paginated_items, pagination = _paginate_items(items, request)

        return Response({
            'success': True,
            'message': f'Корзина обновлена. Полностью удалено позиций: {len(removed_info)}, частично изменено: {len(modified_info)}',
            'removed_items': removed_info,
            'modified_items': modified_info,
            'basket': {
                'store_id': store.id,
                'store_name': store.name,
                'owner_name': store.owner_name,
                'store_phone': store.phone,
                'is_empty': len(items) == 0,
                'orders_count': orders.count(),
                'order_ids': list(orders.values_list('id', flat=True)),
                'items': paginated_items,
                'pagination': pagination,
                'totals': {
                    'piece_count': piece_count,
                    'weight_total': str(int(weight_total) if weight_total == int(weight_total) else weight_total),
                    'total_amount': str(total_amount),
                }
            }
        })

    @extend_schema(
        summary="Подтвердить корзину",
        description="""
                Партнёр подтверждает корзину магазина с указанием предоплаты.

                ВАЖНО: Перед подтверждением партнёр должен отредактировать корзину
                через /basket/remove/ (удалить ненужные товары).

                WORKFLOW:
                1. Партнёр уже отредактировал корзину (remove_from_basket)
                2. Партнёр вводит сумму предоплаты (если магазин заплатил заранее)
                3. Все IN_TRANSIT заказы → ACCEPTED
                4. Товары переносятся в инвентарь магазина
                5. Создаётся долг = сумма_заказов - предоплата
                6. Корзина очищается (заказы переходят в статус ACCEPTED)
                """,
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'prepayment_amount': {
                        'type': 'number',
                        'default': 0,
                        'description': 'Сумма предоплаты (если магазин заплатил заранее)',
                        'example': 5000
                    }
                }
            }
        },
        responses={
            200: OpenApiResponse(description="Корзина подтверждена, создан долг"),
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

        # Параметр предоплаты
        prepayment_amount = request.data.get('prepayment_amount', 0)

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

        # Получаем IN_TRANSIT заказы.
        # order_by('id') обязателен: без детерминированного порядка
        # select_for_update может вызвать deadlock при параллельных запросах.
        orders = list(StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).order_by('id').select_for_update().prefetch_related('items__product'))

        if not orders:
            return Response(
                {'error': 'Нет заказов для подтверждения'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =====================================================================
        # 1. РАСЧЁТ ОБЩЕЙ СУММЫ И ДОЛГА
        # =====================================================================
        total_amount = sum(order.total_amount for order in orders)

        if total_amount == Decimal('0'):
            return Response(
                {'error': 'Корзина пуста — все товары были удалены'},
                status=status.HTTP_400_BAD_REQUEST
            )

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
        # 2. ПОДТВЕРЖДЕНИЕ ЗАКАЗОВ И ПЕРЕНОС В ИНВЕНТАРЬ
        # =====================================================================
        confirmed_orders = []
        confirmed_at = timezone.now()  # Одно время для всех заказов
        remaining_prepayment = prepayment_amount

        try:
            for idx, order in enumerate(orders):
                # Пропорциональное распределение предоплаты.
                # Последний заказ получает остаток, чтобы sum(prepayment_amount) == prepayment_amount.
                if total_amount > 0:
                    is_last = (idx == len(orders) - 1)
                    if is_last:
                        order_prepayment = remaining_prepayment
                    else:
                        order_prepayment = (
                            (order.total_amount / total_amount) * prepayment_amount
                        ).quantize(Decimal('0.01'))
                        remaining_prepayment -= order_prepayment
                else:
                    order_prepayment = Decimal('0')

                order_debt = (order.total_amount - order_prepayment).quantize(Decimal('0.01'))

                old_status = order.status
                order.status = StoreOrderStatus.ACCEPTED
                order.partner = user
                order.confirmed_by = user
                order.confirmed_at = confirmed_at
                order.prepayment_amount = order_prepayment
                order.debt_amount = order_debt

                order.save(update_fields=[
                    'status', 'partner', 'confirmed_by', 'confirmed_at',
                    'prepayment_amount', 'debt_amount'
                ])

                # ✅ КРИТИЧНО: Списываем из PartnerInventory и переносим в StoreInventory
                # order_by('product_id') обязателен: детерминированный порядок блокировок
                # PartnerInventory предотвращает дедлок при параллельных подтверждениях.
                for item in order.items.select_related('product').order_by('product_id'):
                    PartnerInventoryService.complete_reservation(
                        partner=user,
                        product=item.product,
                        quantity=item.quantity,
                        is_bonus=item.is_bonus,
                    )
                    StoreInventoryService.add_to_inventory(
                        store=store,
                        product=item.product,
                        quantity=item.quantity,
                        is_bonus=item.is_bonus,
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

            # =================================================================
            # 3. ОБНОВЛЕНИЕ ДОЛГА МАГАЗИНА
            # =================================================================
            Store.objects.filter(pk=store.pk).update(debt=F('debt') + total_debt)
            store.refresh_from_db()

        except ValidationError as e:
            # Гарантируем откат транзакции (исключение поймано внутри atomic-блока)
            transaction.set_rollback(True)
            message = ', '.join(e.messages) if e.messages else str(e)
            return Response(
                {'error': message},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        })

    @extend_schema(
        summary="Передать товары из инвентаря партнёра в магазин",
        description="""
            Партнёр передаёт товары ИЗ СВОЕГО инвентаря напрямую в магазин.
            
            Это отдельный endpoint для ручного сбора, когда партнёр:
            1. Выбирает магазин
            2. Выбирает товары из своего инвентаря
            3. Подтверждает передачу через этот endpoint
            
            WORKFLOW:
            1. Проверяется наличие товаров в PartnerInventory
            2. Товары перемещаются: PartnerInventory → StoreInventory
            3. Создаётся заказ со статусом ACCEPTED (order_type='manual')
            4. Создаётся долг магазина
            """,
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'items': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'product_id': {'type': 'integer'},
                                'quantity': {'type': 'number'},
                                'price': {'type': 'number', 'description': 'Опционально, если не указана - берётся из товара'}
                            }
                        }
                    },
                    'prepayment_amount': {'type': 'number', 'default': 0},
                    'notes': {'type': 'string'}
                }
            }
        },
        responses={
            200: OpenApiResponse(description="Товары переданы, создан заказ"),
            400: OpenApiResponse(description="Ошибка валидации"),
            403: OpenApiResponse(description="Только партнёры"),
        },
    )
    @action(detail=True, methods=['post'], url_path='partner-basket/confirm')
    @transaction.atomic
    def confirm_partner_basket(self, request: Request, pk=None) -> Response:
        """
        Партнёр передаёт товары из своего инвентаря в магазин.

        POST /api/stores/stores/{id}/partner-basket/confirm/
        Body: {
            "items": [
                {"product_id": 1, "quantity": 10},
                {"product_id": 2, "quantity": 5, "price": 200.00}
            ],
            "prepayment_amount": 0,
            "notes": "Ручной сбор"
        }
        """
        store = self.get_object()
        user = request.user

        if user.role != 'partner':
            return Response(
                {'error': 'Только партнёры могут передавать товары из своего инвентаря'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Парсинг входных данных
        items = request.data.get('items', [])
        prepayment_amount = request.data.get('prepayment_amount', 0)
        notes = request.data.get('notes', '')

        if not items:
            return Response(
                {'error': 'Не указаны товары для передачи'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            prepayment_amount = Decimal(str(prepayment_amount))
        except (ValueError, TypeError):
            return Response(
                {'error': 'Некорректное значение prepayment_amount'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Импортируем сервис и модели
            from orders.services import ManualOrderService, OrderItemData
            from products.models import Product

            # Преобразуем данные товаров
            items_data = []
            for item in items:
                product_id = item.get('product_id')
                quantity = item.get('quantity')
                price = item.get('price')

                if not product_id or quantity is None:
                    continue

                items_data.append(
                    OrderItemData(
                        product_id=product_id,
                        quantity=Decimal(str(quantity)),
                        price=Decimal(str(price)) if price else None,
                        is_bonus=item.get('is_bonus', False)
                    )
                )

            if not items_data:
                return Response(
                    {'error': 'Не указаны валидные товары'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Создаём заказ через сервис (товары переносятся автоматически)
            order = ManualOrderService.create_manual_order(
                partner=user,
                store=store,
                items=items_data,
                prepayment_amount=prepayment_amount,
                notes=notes
            )

            return Response({
                'success': True,
                'message': f'Товары успешно переданы магазину "{store.name}"',
                'order_id': order.id,
                'order_type': order.order_type,
                'total_amount': float(order.total_amount),
                'prepayment': float(order.prepayment_amount),
                'debt_amount': float(order.debt_amount),
                'items_count': order.items.count(),
            })

        except ValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'], url_path='inventory')
    def inventory(self, request: Request, pk=None) -> Response:
        """
        Инвентарь магазина (товары из ACCEPTED заказов).

        GET /api/stores/stores/{id}/inventory/

        Возвращает товары в формате корзины с items и totals.
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

        inventory_qs = StoreInventory.objects.filter(
            store=store,
            quantity__gt=0
        ).select_related('product').prefetch_related('product__images')

        if not inventory_qs.exists():
            return Response({
                'store_id': store.id,
                'store_name': store.name,
                'is_empty': True,
                'items_count': 0,
                'items': [],
                'totals': {
                    'piece_count': 0,
                    'weight_total': '0',
                    'total_amount': '0',
                }
            })

        items, totals = _build_inventory_items(inventory_qs)
        paginated_items, pagination = _paginate_items(items, request)

        return Response({
            'store_id': store.id,
            'store_name': store.name,
            'is_empty': False,
            'items_count': len(items),
            'items': paginated_items,
            'pagination': pagination,
            'totals': totals,
        })

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
                'required': ['product_id', 'quantity'],
                'properties': {
                    'product_id': {'type': 'integer', 'description': 'ID товара из инвентаря'},
                    'quantity': {'type': 'number', 'description': 'Количество брака'},
                    'reason': {'type': 'string', 'description': 'Причина брака (необязательно)'}
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
        weight = request.data.get('weight')
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

        # Валидация weight (если передан)
        if weight is not None:
            try:
                weight = Decimal(str(weight))
            except (ValueError, TypeError):
                return Response(
                    {'error': 'Некорректное значение weight'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if weight < Decimal('0.1'):
                return Response(
                    {'error': 'Минимальный вес: 0.1 кг'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Проверка наличия товара в инвентаре (select_for_update исключает race condition
        # при параллельных запросах на брак одного и того же товара)
        try:
            inventory_item = StoreInventory.objects.select_related('product').select_for_update().get(
                store=store,
                product_id=product_id
            )
        except StoreInventory.DoesNotExist:
            return Response(
                {'error': 'Товар не найден в инвентаре магазина'},
                status=status.HTTP_404_NOT_FOUND
            )

        product = inventory_item.product

        # Для весовых товаров: если weight не передан, используем quantity как вес
        if product.is_weight_based and not weight:
            weight = quantity

        # Валидация weight для весовых товаров (на всякий случай)
        if product.is_weight_based and not weight:
            return Response(
                {'error': 'Для весовых товаров обязательно указать weight (вес в кг)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not product.is_weight_based and weight:
            weight = None  # Штучные товары не имеют веса

        if quantity > inventory_item.quantity:
            return Response(
                {'error': f'Недостаточно товара. Доступно: {inventory_item.quantity}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        price = product.final_price

        # Находим последний ACCEPTED заказ для привязки брака.
        # Фильтруем по партнёру: брак атрибутируется его заказам в статистике.
        order_qs = StoreOrder.objects.filter(store=store, status=StoreOrderStatus.ACCEPTED)
        if user.role == 'partner':
            order_qs = order_qs.filter(partner=user)
        last_order = order_qs.order_by('-confirmed_at').first()

        if not last_order:
            return Response(
                {'error': 'Нет подтверждённых заказов для привязки брака'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Создаём запись о браке (сумма рассчитается в save автоматически)
        defect = DefectiveProduct.objects.create(
            order=last_order,
            product=product,
            quantity=quantity,
            weight=weight,
            price=price,
            reason=reason,
            status=DefectiveProduct.DefectStatus.APPROVED,
            reported_by=user,  # Может быть None если reported_by не используется в этой версии
            reviewed_by=user,
        )

        # Берем рассчитанную сумму из модели
        defect_amount = defect.total_amount

        # Уменьшаем инвентарь атомарно через F() — без race condition
        StoreInventory.objects.filter(pk=inventory_item.pk).update(
            quantity=F('quantity') - quantity,
            last_updated=timezone.now(),
        )
        inventory_item.refresh_from_db(fields=['quantity'])
        if inventory_item.quantity <= Decimal('0'):
            inventory_item.delete()

        # Уменьшаем долг магазина, но НЕ ниже 0 (ТЗ: дефект не может уменьшить долг ниже 0)
        from django.db.models import Case, When, Value, DecimalField as _DecimalField
        debt_before = store.debt
        actual_debt_reduction = min(defect_amount, debt_before)
        defect_credit = defect_amount - actual_debt_reduction  # избыток сверх долга

        Store.objects.filter(pk=store.pk).update(
            debt=Case(
                When(debt__gte=defect_amount, then=F('debt') - defect_amount),
                default=Value(Decimal('0')),
                output_field=_DecimalField(max_digits=14, decimal_places=2),
            )
        )
        store.refresh_from_db()

        if defect_credit > 0:
            message = (
                f'Брак зафиксирован. Долг уменьшен на {actual_debt_reduction} сом. '
                f'Сумма брака ({defect_amount} сом) превысила долг — '
                f'излишек {defect_credit} сом не учтён в долге.'
            )
        else:
            message = f'Брак зафиксирован. Долг уменьшен на {defect_amount} сом.'

        return Response({
            'success': True,
            'message': message,
            'defect': {
                'id': defect.id,
                'product_id': product_id,
                'product_name': product.name,
                'is_weight_based': product.is_weight_based,
                'unit': product.unit,
                'quantity': float(quantity),
                'price': float(price),
                'total_amount': float(defect_amount),
                'actual_debt_reduction': float(actual_debt_reduction),
                'defect_credit': float(defect_credit),
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
    @transaction.atomic
    def pay_store_debt(self, request: Request, pk=None) -> Response:
        """
        Погашение долга магазина (ТЗ v2.0).

        POST /api/stores/{store_id}/pay-debt/

        Body: {
            "amount": 50000000,
            "comment": "Частичное погашение долга",
            "partner_id": 5  // опционально, только для админа
        }

        ВАЖНО:
        - Уменьшает ОБЩИЙ долг магазина (store.debt)
        - НЕ привязано к конкретному заказу
        - Может погашать:
          * Магазин (себе)
          * Партнёр (за магазин)
          * Админ (корректировка, может указать partner_id)

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

        # Блокируем строку магазина до проверки долга,
        # чтобы исключить race condition при параллельных платежах
        store = Store.objects.select_for_update().get(pk=store.pk)

        if amount > store.debt:
            return Response(
                {
                    'error': f'Сумма погашения ({amount} сом) превышает '
                             f'долг магазина ({store.debt} сом)'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================================
        # ОПРЕДЕЛЕНИЕ ПОЛУЧАТЕЛЯ
        # =========================================================================

        paid_by = request.user
        received_by = None

        if request.user.role == 'partner':
            # Партнёр погашает долг магазина ��� получатель он сам
            received_by = request.user
        elif request.user.role == 'admin':
            # Админ может указат�� партнёра-получателя
            target_partner_id = request.data.get('partner_id')
            if target_partner_id:
                from users.models import User
                try:
                    received_by = User.objects.get(pk=target_partner_id, role='partner')
                except User.DoesNotExist:
                    return Response(
                        {'error': f'Партнёр с ID {target_partner_id} не найден'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

        # =========================================================================
        # ОБНОВЛЕНИЕ ДОЛГА МАГАЗИНА
        # =========================================================================

        Store.objects.filter(pk=store.pk).update(
            debt=F('debt') - amount,
            total_paid=F('total_paid') + amount
        )

        # Why: outstanding_debt каждого заказа считается как debt_amount - paid_amount.
        # Если не обновлять paid_amount, то после погашения через pay-debt заказы
        # продолжают показывать полный долг, и ту же сумму собирают повторно.
        remaining = amount
        unpaid_orders = (
            StoreOrder.objects
            .select_for_update()
            .filter(store=store, status=StoreOrderStatus.ACCEPTED)
            .filter(debt_amount__gt=F('paid_amount'))
            .order_by('confirmed_at', 'id')
        )
        for order in unpaid_orders:
            if remaining <= Decimal('0'):
                break
            outstanding = order.debt_amount - order.paid_amount
            apply = min(outstanding, remaining)
            StoreOrder.objects.filter(pk=order.pk).update(
                paid_amount=F('paid_amount') + apply,
            )
            remaining -= apply

        store.refresh_from_db()

        # =========================================================================
        # СОЗДАНИЕ ЗАПИСИ О ПОГАШЕНИИ
        # =========================================================================

        payment = DebtPayment.objects.create(
            store=store,
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
# ДОЛГИ ПАРТНЁРА
# =============================================================================

class PartnerDebtViewSet(viewsets.ViewSet):
    """
    Просмотр долгов магазинов перед партнёром.

    **Permissions:** IsAuthenticated (партнёр видит свои, админ — все)

    **Endpoints:**
    - GET /api/stores/partner-debts/ — список магазинов-должников
    - GET /api/stores/partner-debts/{store_id}/ — детали долга магазина
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Список магазинов-должников партнёра",
        description=(
            "Возвращает список магазинов, у ��оторых есть долг перед партнёром.\n"
            "Партнёр видит только свои долги. Админ может фильтровать по partner_id."
        ),
        parameters=[
            OpenApiParameter(
                name='partner_id', type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID партнёра (только для админа)', required=False,
            ),
        ],
    )
    def list(self, request: Request) -> Response:
        """GET /api/stores/partner-debts/"""
        from django.db.models import Sum, Value
        from django.db.models.functions import Coalesce
        from orders.models import DebtPayment

        user = request.user

        # Определяем партнёра
        if user.role == 'admin':
            partner_id = request.query_params.get('partner_id')
            if partner_id:
                try:
                    partner_filter = {'partner_id': int(partner_id)}
                except (ValueError, TypeError):
                    return Response(
                        {'error': 'partner_id должен быть числом'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                # Админ без фильтра — все партнёры
                partner_filter = {'partner__isnull': False}
        elif user.role == 'partner':
            partner_filter = {'partner': user}
        else:
            return Response(
                {'error': 'Доступно только для партнёров и админов'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Агрегируем данные по магазинам
        store_debts = (
            StoreOrder.objects.filter(
                status=StoreOrderStatus.ACCEPTED,
                **partner_filter,
            )
            .values('store_id', 'store__name', 'store__address', 'store__phone')
            .annotate(
                total_orders_amount=Coalesce(Sum('total_amount'), Value(Decimal('0'))),
                total_prepayment=Coalesce(Sum('prepayment_amount'), Value(Decimal('0'))),
            )
            .order_by('store__name')
        )

        results = []
        for item in store_debts:
            store_id = item['store_id']

            # Погашения через DebtPayment для этого партнёра и магазина
            # Два типа: через заказ (старые) и напрямую к магазину (новые)
            from django.db.models import Q
            store_q = Q(order__store_id=store_id, order__status=StoreOrderStatus.ACCEPTED)
            direct_q = Q(order__isnull=True, store_id=store_id)

            if user.role == 'partner':
                debt_payments_qs = DebtPayment.objects.filter(
                    (store_q & Q(order__partner=user)) |
                    (direct_q & Q(received_by=user))
                )
            elif 'partner_id' in partner_filter:
                pid = partner_filter['partner_id']
                debt_payments_qs = DebtPayment.objects.filter(
                    (store_q & Q(order__partner_id=pid)) |
                    (direct_q & Q(received_by_id=pid))
                )
            else:
                debt_payments_qs = DebtPayment.objects.filter(store_q | direct_q)

            total_paid_debt = debt_payments_qs.aggregate(
                total=Coalesce(Sum('amount'), Value(Decimal('0')))
            )['total']

            total_orders = item['total_orders_amount']
            total_prepayment = item['total_prepayment']
            outstanding = total_orders - total_prepayment - total_paid_debt
            if outstanding < Decimal('0'):
                outstanding = Decimal('0')

            results.append({
                'store_id': store_id,
                'store_name': item['store__name'],
                'store_address': item['store__address'],
                'store_phone': item['store__phone'],
                'total_orders_amount': float(total_orders),
                'total_prepayment': float(total_prepayment),
                'total_paid_debt': float(total_paid_debt),
                'outstanding_debt': float(outstanding),
            })

        # Фильтруем магазины с 0 долгом (если нет query param show_all)
        show_all = request.query_params.get('show_all', 'false').lower() == 'true'
        if not show_all:
            results = [r for r in results if r['outstanding_debt'] > 0]

        return Response(results)

    @extend_schema(
        summary="Детали долга магазина перед партнёром",
        description=(
            "Возвращает: сумму заказов, предоплату, погашения и остаток долга "
            "для конкретного магазина перед партнёром."
        ),
        parameters=[
            OpenApiParameter(
                name='partner_id', type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID партнёра (только для админа)', required=False,
            ),
        ],
    )
    def retrieve(self, request: Request, pk=None) -> Response:
        """GET /api/stores/partner-debts/{store_id}/"""
        from django.db.models import Sum, Value
        from django.db.models.functions import Coalesce
        from orders.models import DebtPayment
        from orders.serializers import DebtPaymentSerializer

        user = request.user
        store_id = pk

        # Проверяем магазин
        try:
            store = Store.objects.get(pk=store_id)
        except Store.DoesNotExist:
            return Response(
                {'error': f'Магазин с ID {store_id} не найден'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Определяем фильтр партнёра
        # Партнёр и админ видят долги ВСЕХ партнёров для этого магазина,
        # но могут фильтровать по partner_id
        if user.role not in ('admin', 'partner'):
            return Response(
                {'error': 'Доступно только для партнёров и админов'},
                status=status.HTTP_403_FORBIDDEN
            )

        partner_id = request.query_params.get('partner_id')
        if partner_id:
            try:
                partner_filter = {'partner_id': int(partner_id)}
            except (ValueError, TypeError):
                return Response(
                    {'error': 'partner_id должен быть числом'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            partner_filter = {'partner__isnull': False}

        # Заказы
        orders_qs = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED,
            **partner_filter,
        ).order_by('-confirmed_at')

        totals = orders_qs.aggregate(
            total_orders_amount=Coalesce(Sum('total_amount'), Value(Decimal('0'))),
            total_prepayment=Coalesce(Sum('prepayment_amount'), Value(Decimal('0'))),
        )

        # Погашения (два типа: через заказ и напрямую)
        from django.db.models import Q
        store_q = Q(order__store=store, order__status=StoreOrderStatus.ACCEPTED)
        direct_q = Q(order__isnull=True, store=store)

        if 'partner_id' in partner_filter:
            pid = partner_filter['partner_id']
            debt_payments_qs = DebtPayment.objects.filter(
                (store_q & Q(order__partner_id=pid)) |
                (direct_q & Q(received_by_id=pid))
            )
        else:
            debt_payments_qs = DebtPayment.objects.filter(store_q | direct_q)

        total_paid_debt = debt_payments_qs.aggregate(
            total=Coalesce(Sum('amount'), Value(Decimal('0')))
        )['total']

        outstanding = (
            totals['total_orders_amount']
            - totals['total_prepayment']
            - total_paid_debt
        )
        if outstanding < Decimal('0'):
            outstanding = Decimal('0')

        # Последние погашения
        recent_payments = debt_payments_qs.select_related(
            'paid_by', 'received_by'
        ).order_by('-created_at')[:20]

        payments_data = DebtPaymentSerializer(recent_payments, many=True).data

        # Краткая информация о заказах
        orders_summary = []
        for order in orders_qs[:50]:
            orders_summary.append({
                'id': order.id,
                'order_type': order.order_type,
                'total_amount': float(order.total_amount),
                'prepayment_amount': float(order.prepayment_amount),
                'debt_amount': float(order.debt_amount),
                'paid_amount': float(order.paid_amount),
                'outstanding_debt': float(order.outstanding_debt),
                'confirmed_at': order.confirmed_at,
                'created_at': order.created_at,
            })

        return Response({
            'store': {
                'id': store.id,
                'name': store.name,
                'address': store.address,
                'phone': store.phone,
            },
            'total_orders_amount': float(totals['total_orders_amount']),
            'total_prepayment': float(totals['total_prepayment']),
            'total_paid_debt': float(total_paid_debt),
            'outstanding_debt': float(outstanding),
            'recent_payments': payments_data,
            'orders': orders_summary,
        })


# =============================================================================
# ВЫБОР МАГАЗИНА
# =============================================================================

class SelectStoreView(APIView):
    """
    Выбрать магазин для работы (только для role='store').

    ✅ ИСПРАВЛЕНО v3.1:
    - Поддерживает store_id из body И query params.
    - Обработка race condition (IntegrityError) с retry
    - Rate limiting: 5 запросов в минуту (защита от параллельных запросов)
    """

    permission_classes = [IsAuthenticated, IsStore]
    throttle_classes = [StoreSelectionThrottle]  # ✅ Rate limiting для защиты от race condition

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
        """Выбрать магазин с защитой от race condition."""
        from django.db import IntegrityError
        import logging
        logger = logging.getLogger(__name__)
        
        # ✅ Поддержка store_id из query params ИЛИ body
        store_id = request.query_params.get('store_id') or request.data.get('store_id')

        if not store_id:
            return Response(
                {'error': 'store_id обязателен (в body или query params)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Валидация
        serializer = StoreSelectionCreateSerializer(data={'store_id': store_id})
        serializer.is_valid(raise_exception=True)
        
        validated_store_id = serializer.validated_data['store_id']

        try:
            selection = StoreSelectionService.select_store(
                user=request.user,
                store_id=validated_store_id
            )
            output_serializer = StoreSelectionSerializer(selection)
            return Response(output_serializer.data, status=status.HTTP_200_OK)
            
        except IntegrityError as e:
            # ✅ Race condition detected - retry with atomic transaction
            logger.warning(f"Race condition in select_store for user {request.user.id}: {e}")
            
            try:
                with transaction.atomic():
                    # Сбрасываем все активные выборы принудительно
                    StoreSelection.objects.filter(
                        user=request.user,
                        is_current=True
                    ).update(is_current=False, deselected_at=timezone.now())
                    
                    # Retry selection
                    selection = StoreSelectionService.select_store(
                        user=request.user,
                        store_id=validated_store_id
                    )
                    
                output_serializer = StoreSelectionSerializer(selection)
                return Response(output_serializer.data, status=status.HTTP_200_OK)
                
            except Exception as retry_error:
                logger.error(f"Failed to select store after retry for user {request.user.id}: {retry_error}")
                return Response(
                    {'error': 'Не удалось выбрать магазин. Попробуйте еще раз.'},
                    status=status.HTTP_409_CONFLICT  # 409 Conflict для race condition
                )



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


# =============================================================================
# PARTNER INVENTORY (v3.0)
# =============================================================================
@extend_schema_view(
    list=extend_schema(
        summary="Список инвентаря партнёра",
        description="Получить весь инвентарь партнёра с информацией о товарах",
        tags=['Partners v3.0']
    ),
    retrieve=extend_schema(
        summary="Детали позиции инвентаря",
        description="Получить подробную информацию о позиции в инвентаре",
        tags=['Partners v3.0']
    ),
    reserve=extend_schema(
        summary="Зарезервировать товар",
        description="Зарезервировать указанное количество товара для заказа",
        tags=['Partners v3.0'],
        request=ReserveQuantitySerializer,
        responses={
            200: PartnerInventorySerializer,
            400: OpenApiTypes.OBJECT
        }
    ),
    release=extend_schema(
        summary="Освободить резерв",
        description="Освободить зарезервированное количество товара",
        tags=['Partners v3.0'],
        request=ReleaseQuantitySerializer,
        responses={
            200: PartnerInventorySerializer,
            400: OpenApiTypes.OBJECT
        }
    )
)
class PartnerInventoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления инвентарём партнёра (v3.0).

    GET /api/stores/partner-inventory/ — список товаров в формате корзины (items + totals)

    Функциональность:
    - Просмотр инвентаря (формат корзины)
    - Резервирование товаров для заказов
    - Освобождение резерва при отмене

    Permissions:
    - Только партнёры (IsPartner)
    - Каждый партнёр видит только свой инвентарь
    """

    permission_classes = [IsAuthenticated, IsPartner]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        """Получить инвентарь ТОЛЬКО текущего партнёра."""
        if getattr(self, 'swagger_fake_view', False):
            return PartnerInventory.objects.none()

        return PartnerInventory.objects.filter(
            partner=self.request.user
        ).select_related('product').prefetch_related('product__images', 'product__additional_prices').order_by('product__name')

    def get_serializer_class(self):
        """Выбрать сериализатор в зависимости от действия."""
        if self.action == 'reserve':
            return ReserveQuantitySerializer
        elif self.action == 'release':
            return ReleaseQuantitySerializer
        return PartnerInventorySerializer

    def list(self, request: Request) -> Response:
        """Список товаров инвентаря партнёра в формате корзины."""
        partner = request.user

        inventory_qs = PartnerInventory.objects.filter(
            partner=partner,
            quantity__gt=F('reserved_quantity')
        ).select_related('product').prefetch_related('product__images', 'product__additional_prices')

        if not inventory_qs.exists():
            return Response({
                'partner_id': partner.id,
                'is_empty': True,
                'items_count': 0,
                'items': [],
                'totals': {
                    'piece_count': 0,
                    'weight_total': '0',
                    'total_amount': '0',
                }
            })

        items, totals = _build_inventory_items(inventory_qs, use_available_quantity=True)
        paginated_items, pagination = _paginate_items(items, request)

        return Response({
            'partner_id': partner.id,
            'is_empty': False,
            'items_count': len(items),
            'items': paginated_items,
            'pagination': pagination,
            'totals': totals,
        })

    @action(detail=True, methods=['post'], url_path='reserve')
    def reserve(self, request: Request, pk=None) -> Response:
        """
        Зарезервировать товар из инвентаря.

        Используется при создании ручного заказа (manual order).
        Резервирование предотвращает двойную продажу.
        """
        inventory = self.get_object()
        serializer = ReserveQuantitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quantity = serializer.validated_data['quantity']

        try:
            PartnerInventoryService.reserve_quantity(
                partner=request.user,
                product=inventory.product,
                quantity=quantity
            )

            # Обновить объект
            inventory.refresh_from_db()

            return Response(
                {
                    'message': 'Товар успешно зарезервирован',
                    'inventory': PartnerInventorySerializer(inventory).data
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'], url_path='release')
    @transaction.atomic
    def release(self, request: Request, pk=None) -> Response:
        """
        Вернуть товар из инвентаря партнёра в каталог админа.

        POST /api/stores/partner-inventory/{id}/release/
        Body: {"quantity": 10}
        
        Workflow:
        1. Уменьшает quantity в PartnerInventory
        2. Увеличивает stock_quantity в Product (каталог админа)
        """
        inventory = self.get_object()
        serializer = ReleaseQuantitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quantity = serializer.validated_data['quantity']

        try:
            # 1. Удалить из инвентаря партнёра
            PartnerInventoryService.remove_from_inventory(
                partner=request.user,
                product=inventory.product,
                quantity=quantity
            )

            # 2. Вернуть на склад админа атомарно
            product = inventory.product
            Product.objects.filter(pk=product.pk).update(
                stock_quantity=F('stock_quantity') + quantity,
                is_available=True,
            )

            # Обновить объект (может быть удалён если quantity=0)
            try:
                inventory.refresh_from_db()
                inventory_data = PartnerInventorySerializer(inventory).data
            except PartnerInventory.DoesNotExist:
                inventory_data = None

            return Response(
                {
                    'message': f'Товар успешно возвращён в каталог ({quantity} шт/кг)',
                    'returned_to_catalog': float(quantity),
                    'inventory': inventory_data
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

class StoreInventoryViewSet(viewsets.ViewSet):
    """
    ViewSet для инвентаря магазина.

    GET /api/stores/store-inventory/ — список товаров в формате корзины (items + totals)

    Permissions:
    - Только пользователи с ролью store (IsStore)
    - Магазин видит инвентарь только своего выбранного магазина
    """

    permission_classes = [IsAuthenticated, IsStore]

    def list(self, request: Request) -> Response:
        """Список товаров инвентаря магазина в формате корзины."""
        store = StoreSelectionService.get_current_store(request.user)
        if not store:
            return Response(
                {'error': 'Сначала выберите магазин'},
                status=status.HTTP_400_BAD_REQUEST
            )

        inventory_qs = StoreInventory.objects.filter(
            store=store,
            quantity__gt=0
        ).select_related('product').prefetch_related('product__images')

        if not inventory_qs.exists():
            return Response({
                'store_id': store.id,
                'store_name': store.name,
                'is_empty': True,
                'items_count': 0,
                'items': [],
                'totals': {
                    'piece_count': 0,
                    'weight_total': '0',
                    'total_amount': '0',
                }
            })

        items, totals = _build_inventory_items(inventory_qs)
        paginated_items, pagination = _paginate_items(items, request)

        return Response({
            'store_id': store.id,
            'store_name': store.name,
            'is_empty': False,
            'items_count': len(items),
            'items': paginated_items,
            'pagination': pagination,
            'totals': totals,
        })
