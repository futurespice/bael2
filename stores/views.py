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

from django.db.models import QuerySet
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.core.exceptions import ValidationError
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
        """Получение списка магазинов в зависимости от роли."""
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

        return queryset.select_related('region', 'city').order_by('name')

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


    def freeze(self, request: Request, pk=None) -> Response:
        """
        Заморозить (заблокировать) магазин.

        Только для администраторов.

        POST /api/stores/{id}/freeze/

        Request Body:
            {
                "reason": "Нарушение условий работы"  // опционально
            }

        Response (Success):
            {
                "message": "Магазин 'Название' заморожен",
                "store": {
                    "id": 1,
                    "name": "Название",
                    "is_active": false,
                    ...
                }
            }

        Response (Error):
            {
                "error": "Только администратор может замораживать магазины"
            }

        Статус коды:
        - 200: Успешно заморожен
        - 400: Ошибка валидации (например, уже заморожен)
        - 403: Недостаточно прав
        - 404: Магазин не найден
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

        POST /api/stores/{id}/unfreeze/

        Request Body:
            {
                "comment": "Нарушение устранено"  // опционально
            }

        Response (Success):
            {
                "message": "Магазин 'Название' разморожен",
                "store": {
                    "id": 1,
                    "name": "Название",
                    "is_active": true,
                    ...
                }
            }

        Response (Error):
            {
                "error": "Только администратор может размораживать магазины"
            }

        Статус коды:
        - 200: Успешно разморожен
        - 400: Ошибка валидации (например, уже активен)
        - 403: Недостаточно прав
        - 404: Магазин не найден
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


    @action(detail=True, methods=['get'], url_path='inventory')
    def inventory(self, request: Request, pk=None) -> Response:
        """
        Инвентарь магазина.

        GET /api/stores/{id}/inventory/

        КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ v2.0 (требование #11):
        - Магазин НЕ видит инвентарь, пока есть заказы со статусом "В пути"
        - Инвентарь становится виден только после статуса "Принят"
        """
        store = self.get_object()
        user = request.user

        # ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ v2.0: Проверка для магазина
        if user.role == 'store':
            # Импортируем здесь чтобы избежать circular import
            from orders.models import StoreOrder, StoreOrderStatus
            
            # Проверяем есть ли заказы со статусом IN_TRANSIT
            has_in_transit = StoreOrder.objects.filter(
                store=store,
                status=StoreOrderStatus.IN_TRANSIT
            ).exists()
            
            if has_in_transit:
                return Response(
                    {
                        'error': 'Инвентарь недоступен',
                        'message': 'У вас есть заказы в статусе "В пути". '
                                   'Инвентарь станет доступен после подтверждения заказов партнёром.'
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

    @action(detail=True, methods=['get'], url_path='inventory-with-bonuses')
    def inventory_with_bonuses(self, request: Request, pk=None) -> Response:
        """
        Инвентарь магазина с расчётом бонусов (ТЗ v2.0).

        GET /api/stores/{id}/inventory-with-bonuses/

        ЛОГИКА БОНУСОВ:
        - Каждый 21-й товар бесплатно (20 платных + 1 бонусный)
        - Бонусы только для штучных товаров с is_bonus=True
        - Бонусы считаются по НАКОПЛЕННОМУ количеству в инвентаре

        ПРИМЕР:
        - Товар "Мороженое" (is_bonus=True)
        - Заказ #1: 15 шт, Заказ #2: 10 шт → Инвентарь: 25
        - Бонусы = 25 // 21 = 1 бонусный
        - Платных = 25 - 1 = 24 шт
        """
        store = self.get_object()
        user = request.user

        # Проверка для магазина: инвентарь скрыт при IN_TRANSIT
        if user.role == 'store':
            from orders.models import StoreOrder, StoreOrderStatus
            
            has_in_transit = StoreOrder.objects.filter(
                store=store,
                status=StoreOrderStatus.IN_TRANSIT
            ).exists()
            
            if has_in_transit:
                return Response(
                    {
                        'error': 'Инвентарь недоступен',
                        'message': 'У вас есть заказы в статусе "В пути". '
                                   'Инвентарь станет доступен после подтверждения заказов партнёром.'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        # Получаем инвентарь с бонусами
        inventory_data = BonusCalculationService.get_inventory_with_bonuses(store)
        summary = BonusCalculationService.get_total_bonuses_summary(store)

        return Response({
            'store_id': store.id,
            'store_name': store.name,
            'inventory': inventory_data,
            'bonus_summary': summary
        })

    # Файл: stores/views.py
    # Добавить этот action в StoreViewSet

    @action(
        detail=True,
        methods=['post'],
        url_path='inventory/confirm',
        permission_classes=[IsPartner]
    )
    def confirm_inventory(self, request: Request, pk=None) -> Response:
        """
        Партнёр подтверждает ВЕСЬ инвентарь магазина одним действием (ТЗ v2.0).

        POST /api/stores/{store_id}/inventory/confirm/

        Body: {
            "prepayment_amount": 5000000,
            "items_to_remove": [
                {
                    "product_id": 1,
                    "quantity": 100
                }
            ]
        }

        Параметры:
        - prepayment_amount: Предоплата (может быть 0, не больше суммы инвентаря)
        - items_to_remove: Массив товаров для удаления (опционально, может быть пустым)
          - product_id: ID товара
          - quantity: Количество для удаления

        Результат:
        - Удаляет указанные товары из инвентаря
        - ВСЕ заказы магазина "В пути" → "Принят"
        - Долг магазина = сумма инвентаря - предоплата
        """
        from decimal import Decimal
        from django.db.models import F, Sum
        from django.utils import timezone
        from rest_framework import status
        from orders.models import (
            StoreOrder,
            StoreOrderStatus,
            OrderHistory,
            OrderType,
            StoreOrderItem
        )
        from stores.models import StoreInventory, Store
        from stores.services import BonusCalculationService, StoreInventoryService

        store = self.get_object()

        # Валидация партнёра
        if request.user.role != 'partner':
            return Response(
                {'error': 'Только партнёры могут подтверждать инвентарь'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Валидация данных
        prepayment_amount = Decimal(str(request.data.get('prepayment_amount', 0)))
        items_to_remove = request.data.get('items_to_remove', [])

        if prepayment_amount < 0:
            return Response(
                {'error': 'Предоплата не может быть отрицательной'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем все заказы "В пути"
        in_transit_orders = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.IN_TRANSIT
        ).prefetch_related('items__product')

        if not in_transit_orders.exists():
            return Response(
                {'error': 'Нет заказов для подтверждения'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================================
        # УДАЛЕНИЕ ТОВАРОВ ИЗ ИНВЕНТАРЯ (если указаны)
        # =========================================================================

        removed_items_info = []

        if items_to_remove:
            for item_data in items_to_remove:
                try:
                    product_id = int(item_data['product_id'])
                    quantity_to_remove = Decimal(str(item_data['quantity']))

                    if quantity_to_remove <= 0:
                        continue

                    # Находим товар в инвентаре
                    inventory_item = StoreInventory.objects.filter(
                        store=store,
                        product_id=product_id
                    ).first()

                    if not inventory_item:
                        continue

                    # Определяем сколько удалить
                    current_quantity = inventory_item.quantity

                    if quantity_to_remove >= current_quantity:
                        # Удаляем весь товар
                        actual_removed = current_quantity

                        # Удаляем из инвентаря
                        inventory_item.delete()

                        # Удаляем из всех заказов
                        StoreOrderItem.objects.filter(
                            order__in=in_transit_orders,
                            product_id=product_id
                        ).delete()

                    else:
                        # Удаляем частично
                        actual_removed = quantity_to_remove

                        # Уменьшаем количество в инвентаре
                        inventory_item.quantity -= quantity_to_remove
                        inventory_item.save()

                        # Уменьшаем в заказах пропорционально
                        order_items = StoreOrderItem.objects.filter(
                            order__in=in_transit_orders,
                            product_id=product_id
                        )

                        # Распределяем удаление по заказам
                        remaining_to_remove = quantity_to_remove

                        for order_item in order_items:
                            if remaining_to_remove <= 0:
                                break

                            if order_item.quantity <= remaining_to_remove:
                                # Удаляем всю позицию
                                remaining_to_remove -= order_item.quantity
                                order_item.delete()
                            else:
                                # Уменьшаем количество
                                order_item.quantity -= remaining_to_remove
                                order_item.total = order_item.quantity * order_item.price
                                order_item.save()
                                remaining_to_remove = Decimal('0')

                    removed_items_info.append({
                        'product_id': product_id,
                        'product_name': inventory_item.product.name,
                        'requested_quantity': float(quantity_to_remove),
                        'actual_removed': float(actual_removed)
                    })

                except (KeyError, ValueError, TypeError) as e:
                    # Пропускаем некорректные данные
                    continue

        # Пересчитываем суммы заказов после удаления товаров
        for order in in_transit_orders:
            order.recalc_total()

        # Вычисляем общую сумму всех заказов
        total_amount_data = in_transit_orders.aggregate(
            total=Sum('total_amount')
        )
        total_inventory_amount = total_amount_data['total'] or Decimal('0')

        if total_inventory_amount == 0:
            return Response(
                {'error': 'Инвентарь пуст после удаления товаров'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Проверка предоплаты
        if prepayment_amount > total_inventory_amount:
            return Response(
                {
                    'error': f'Предоплата ({prepayment_amount} сом) не может превышать '
                             f'сумму инвентаря ({total_inventory_amount} сом)'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================================
        # ПОДТВЕРЖДЕНИЕ ВСЕХ ЗАКАЗОВ
        # =========================================================================

        confirmed_count = 0
        total_debt = Decimal('0')

        # Распределяем предоплату пропорционально между заказами
        orders_list = list(in_transit_orders)
        remaining_prepayment = prepayment_amount

        for idx, order in enumerate(orders_list):
            # Рассчитываем долю предоплаты для этого заказа
            if idx == len(orders_list) - 1:
                # Последний заказ получает остаток
                order_prepayment = remaining_prepayment
            else:
                # Пропорционально сумме заказа
                if total_inventory_amount > 0:
                    ratio = order.total_amount / total_inventory_amount
                    order_prepayment = (prepayment_amount * ratio).quantize(Decimal('0.01'))
                else:
                    order_prepayment = Decimal('0')
                remaining_prepayment -= order_prepayment

            # Рассчитываем долг
            order_debt = order.total_amount - order_prepayment

            # Обновляем заказ
            order.prepayment_amount = order_prepayment
            order.debt_amount = order_debt
            order.status = StoreOrderStatus.ACCEPTED
            order.partner = request.user
            order.confirmed_by = request.user
            order.confirmed_at = timezone.now()
            order.save()

            total_debt += order_debt
            confirmed_count += 1

            # История
            OrderHistory.objects.create(
                order_type=OrderType.STORE,
                order_id=order.id,
                old_status=StoreOrderStatus.IN_TRANSIT,
                new_status=StoreOrderStatus.ACCEPTED,
                changed_by=request.user,
                comment=(
                    f'Подтверждено партнёром через инвентарь. '
                    f'Сумма заказа: {order.total_amount} сом. '
                    f'Предоплата: {order_prepayment} сом. '
                    f'Долг: {order_debt} сом.'
                )
            )

        # ✅ ИСПРАВЛЕНО: Обновляем долг магазина через update()
        Store.objects.filter(pk=store.pk).update(
            debt=F('debt') + total_debt
        )
        store.refresh_from_db()

        # Получаем обновлённый инвентарь
        inventory = BonusCalculationService.get_inventory_with_bonuses(store)

        return Response({
            'success': True,
            'message': f'Инвентарь подтверждён. Принято заказов: {confirmed_count}',
            'confirmed_orders_count': confirmed_count,
            'total_inventory_amount': float(total_inventory_amount),
            'prepayment_amount': float(prepayment_amount),
            'total_debt_created': float(total_debt),
            'store_total_debt': float(store.debt),
            'removed_items': removed_items_info,
            'inventory': inventory
        })

    # Файл: stores/views.py
    # Добавить этот action в StoreViewSet

    @action(
        detail=True,
        methods=['post'],
        url_path='inventory/report-defect',
        permission_classes=[IsPartner]  # ✅ ИСПРАВЛЕНО: Только партнёр!
    )
    def report_defect_from_inventory(self, request: Request, pk=None) -> Response:
        """
        Партнёр выявляет бракованные товары из инвентаря магазина (ТЗ v2.0).

        POST /api/stores/{store_id}/inventory/report-defect/

        Body: {
            "product_id": 1,
            "quantity": 50,
            "reason": "Товар испорчен при транспортировке"
        }

        ВАЖНО:
        - ПАРТНЁР выявляет брак (не магазин!)
        - Товар выбирается из ИНВЕНТАРЯ магазина
        - Брак сразу ОДОБРЯЕТСЯ (статус APPROVED)
        - Долг магазина СРАЗУ уменьшается

        Workflow:
        1. Партнёр доставил товары магазину
        2. Партнёр обнаружил брак в инвентаре
        3. Партнёр отмечает бракованные товары
        4. Долг магазина автоматически уменьшается
        """
        from decimal import Decimal
        from django.db.models import F
        from rest_framework import status
        from orders.models import DefectiveProduct, StoreOrder, StoreOrderStatus
        from stores.models import StoreInventory, Store

        store = self.get_object()

        # Валидация партнёра
        if request.user.role != 'partner':
            return Response(
                {'error': 'Только партнёры могут выявлять бракованные товары'},
                status=status.HTTP_403_FORBIDDEN
            )

        # =========================================================================
        # ВАЛИДАЦИЯ ДАННЫХ
        # =========================================================================

        product_id = request.data.get('product_id')
        quantity = request.data.get('quantity')
        reason = request.data.get('reason', '')

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

        if not reason or not reason.strip():
            return Response(
                {'error': 'Укажите причину брака'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================================
        # ПРОВЕРКА НАЛИЧИЯ ТОВАРА В ИНВЕНТАРЕ
        # =========================================================================

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

        # Проверяем что количество не превышает имеющееся
        if quantity > inventory_item.quantity:
            return Response(
                {
                    'error': f'В инвентаре только {inventory_item.quantity} единиц товара "{inventory_item.product.name}", '
                             f'а вы заявляете о {quantity}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================================
        # ПОИСК ЗАКАЗА ДЛЯ СВЯЗИ
        # =========================================================================

        # Находим последний подтверждённый заказ магазина с этим товаром
        last_order = StoreOrder.objects.filter(
            store=store,
            status=StoreOrderStatus.ACCEPTED,
            items__product_id=product_id
        ).order_by('-confirmed_at').first()

        if not last_order:
            return Response(
                {
                    'error': f'Не найден подтверждённый заказ с товаром "{inventory_item.product.name}". '
                             'Брак можно отметить только по подтверждённым товарам.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================================
        # СОЗДАНИЕ ЗАПИСИ О БРАКЕ
        # =========================================================================

        # Берём цену из продукта
        price = inventory_item.product.final_price
        total_amount = quantity * price

        # Создаём запись о браке со статусом APPROVED (сразу одобрено партнёром)
        defect = DefectiveProduct.objects.create(
            order=last_order,
            product=inventory_item.product,
            quantity=quantity,
            price=price,
            total_amount=total_amount,
            reason=reason.strip(),
            reported_by=request.user,
            reviewed_by=request.user,  # ✅ Партнёр сам выявил и одобрил
            status=DefectiveProduct.DefectStatus.APPROVED  # ✅ Сразу APPROVED
        )

        # =========================================================================
        # УМЕНЬШЕНИЕ ДОЛГА МАГАЗИНА
        # =========================================================================

        # ✅ Уменьшаем долг заказа
        StoreOrder.objects.filter(pk=last_order.pk).update(
            debt_amount=F('debt_amount') - total_amount
        )
        last_order.refresh_from_db()

        # ✅ Уменьшаем долг магазина
        Store.objects.filter(pk=store.pk).update(
            debt=F('debt') - total_amount
        )
        store.refresh_from_db()

        # =========================================================================
        # УМЕНЬШЕНИЕ КОЛИЧЕСТВА В ИНВЕНТАРЕ
        # =========================================================================

        # Уменьшаем количество бракованного товара в инвентаре
        if quantity >= inventory_item.quantity:
            # Удаляем весь товар из инвентаря
            inventory_item.delete()
        else:
            # Уменьшаем количество
            inventory_item.quantity -= quantity
            inventory_item.save()

        # =========================================================================
        # ИСТОРИЯ ЗАКАЗА
        # =========================================================================

        from orders.models import OrderHistory, OrderType
        OrderHistory.objects.create(
            order_type=OrderType.STORE,
            order_id=last_order.id,
            old_status=last_order.status,
            new_status=last_order.status,
            changed_by=request.user,
            comment=f'Партнёр выявил брак: {inventory_item.product.name} x {quantity} = {total_amount} сом. Долг магазина уменьшен.'
        )

        # =========================================================================
        # ОТВЕТ
        # =========================================================================

        from orders.serializers import DefectiveProductSerializer
        serializer = DefectiveProductSerializer(defect)

        return Response({
            'success': True,
            'message': 'Бракованный товар отмечен. Долг магазина уменьшен.',
            'defect': serializer.data,
            'total_defect_amount': float(total_amount),
            'order_debt_before': float(last_order.debt_amount + total_amount),
            'order_debt_after': float(last_order.debt_amount),
            'store_debt_before': float(store.debt + total_amount),
            'store_debt_after': float(store.debt)
        }, status=status.HTTP_201_CREATED)



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

    POST /api/stores/select/
    Body: {"store_id": 1}
    """

    permission_classes = [IsAuthenticated, IsStore]

    def post(self, request: Request) -> Response:
        """Выбрать магазин."""
        serializer = StoreSelectionCreateSerializer(data=request.data)
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

    POST /api/stores/deselect/
    """

    permission_classes = [IsAuthenticated, IsStore]

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
