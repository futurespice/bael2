# apps/stores/filters.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
import django_filters
from django.db.models import Q
from .models import Store


class StoreFilter(django_filters.FilterSet):
    """
    Фильтры для магазинов.

    Параметры:
    - region: ID региона
    - city: ID города
    - is_active: активность магазина
    - approval_status: статус одобрения
    - debt_min: минимальный долг
    - debt_max: максимальный долг
    - has_debt: только с долгом (исключает нулевые)
    - search: поиск по названию, ИНН, телефону, ФИО владельца
    - ordering: сортировка (debt, -debt, created_at, -created_at, name)
    """

    # География
    region = django_filters.NumberFilter(field_name='region_id')
    city = django_filters.NumberFilter(field_name='city_id')

    # Статусы
    is_active = django_filters.BooleanFilter(field_name='is_active')
    approval_status = django_filters.ChoiceFilter(
        field_name='approval_status',
        choices=[
            ('pending', 'Ожидает'),
            ('approved', 'Принят'),
            ('rejected', 'Отклонён')
        ]
    )

    # Долги
    debt_min = django_filters.NumberFilter(field_name='debt', lookup_expr='gte')
    debt_max = django_filters.NumberFilter(field_name='debt', lookup_expr='lte')

    # ИСПРАВЛЕНИЕ #8: Фильтр "только с долгом"
    # По ТЗ: "если магазин только добавлен и не имеет данных или был
    # полностью погашен долг, то они отсеиваются из этого списка"
    has_debt = django_filters.BooleanFilter(method='filter_has_debt')

    # Поиск
    search = django_filters.CharFilter(method='filter_search')

    # Сортировка
    ordering = django_filters.OrderingFilter(
        fields=(
            ('debt', 'debt'),
            ('created_at', 'created_at'),
            ('name', 'name'),
        ),
        field_labels={
            'debt': 'Долг',
            '-debt': 'Долг (убывание)',
            'created_at': 'Дата создания',
            '-created_at': 'Дата создания (убывание)',
            'name': 'Название',
        }
    )

    class Meta:
        model = Store
        fields = ['region', 'city', 'is_active', 'approval_status',
                  'debt_min', 'debt_max', 'has_debt', 'search']

    def filter_has_debt(self, queryset, name, value):
        """
        Фильтрация магазинов с долгом.

        has_debt=true: только магазины с долгом > 0
        has_debt=false: только магазины без долга (долг = 0)
        """
        if value is True:
            return queryset.filter(debt__gt=0)
        elif value is False:
            return queryset.filter(debt=0)
        return queryset

    def filter_search(self, queryset, name, value):
        """
        Поиск по нескольким полям.

        Ищет по: названию, ИНН, телефону, ФИО владельца, городу.
        """
        if not value:
            return queryset

        return queryset.filter(
            Q(name__icontains=value) |
            Q(inn__icontains=value) |
            Q(phone__icontains=value) |
            Q(owner_name__icontains=value) |
            Q(city__name__icontains=value)
        )


class DebtorStoreFilter(django_filters.FilterSet):
    """
    Специальный фильтр для списка должников.

    По ТЗ (раздел 1.6 и 2.7):
    - Показывает магазины от наибольшего долга до наименьшего
    - Исключает магазины без долга
    - Поддерживает фильтрацию по городам/областям
    """

    region = django_filters.NumberFilter(field_name='region_id')
    city = django_filters.NumberFilter(field_name='city_id')

    # Сортировка по долгу
    sort_by = django_filters.ChoiceFilter(
        method='filter_sort',
        choices=[
            ('debt_desc', 'Долг (убывание)'),
            ('debt_asc', 'Долг (возрастание)'),
        ]
    )

    class Meta:
        model = Store
        fields = ['region', 'city', 'sort_by']

    def filter_sort(self, queryset, name, value):
        """Сортировка по долгу"""
        if value == 'debt_desc':
            return queryset.order_by('-debt')
        elif value == 'debt_asc':
            return queryset.order_by('debt')
        return queryset

    @property
    def qs(self):
        """
        Переопределяем queryset для автоматического исключения
        магазинов без долга.
        """
        parent_qs = super().qs
        # Исключаем магазины без долга
        return parent_qs.filter(debt__gt=0, is_active=True, approval_status='approved')
