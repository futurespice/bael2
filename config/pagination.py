"""
Общая пагинация для всех приложений.

Страница за пределами списка (?page=5 при 3 страницах) возвращает
пустой results с next=null вместо 404 "Неправильная страница" —
мобильное приложение при подгрузке списка не получает ошибку,
а просто видит конец списка. Некорректный номер (?page=abc, ?page=0)
по-прежнему даёт 404.
"""
from django.core.paginator import Page
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination


class LenientPageNumberPagination(PageNumberPagination):
    """PageNumberPagination без 404 для страниц за концом списка (PAGE_SIZE из настроек)."""

    def paginate_queryset(self, queryset, request, view=None):
        try:
            return super().paginate_queryset(queryset, request, view)
        except NotFound:
            page_number = request.query_params.get(self.page_query_param, '')
            if not page_number.isdigit() or int(page_number) < 1:
                raise
            paginator = self.django_paginator_class(queryset, self.get_page_size(request))
            self.request = request
            self.page = Page([], paginator.num_pages + 1, paginator)
            return []


class StandardPagination(LenientPageNumberPagination):
    """Стандартная пагинация: 30 на страницу, ?page_size= до 100."""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100
