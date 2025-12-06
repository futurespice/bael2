"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from django.views.generic import RedirectView
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def health_check(request):
    """Health check endpoint для мониторинга"""
    return JsonResponse({
        'status': 'healthy',
        'service': 'B2B Backend API',
        'version': '1.0.0'
    })


@require_http_methods(["GET"])
def api_root(request):
    """Корневой endpoint API с документацией"""
    return JsonResponse({
        'message': 'B2B Backend API',
        'version': '1.0.0',
        'documentation': {
            'swagger': request.build_absolute_uri('/api/docs/'),
            'redoc': request.build_absolute_uri('/api/redoc/'),
            'schema': request.build_absolute_uri('/api/schema/')
        },
        'endpoints': {
            'auth': request.build_absolute_uri('/api/auth/'),
            'products': request.build_absolute_uri('/api/products/'),
            'stores': request.build_absolute_uri('/api/stores/'),
            'orders': request.build_absolute_uri('/api/orders/'),
            'debts': request.build_absolute_uri('/api/debts/'),
            'bonuses': request.build_absolute_uri('/api/bonuses/'),
            'cost_accounting': request.build_absolute_uri('/api/cost-accounting/'),
            'reports': request.build_absolute_uri('/api/reports/'),
            'regions': request.build_absolute_uri('/api/regions/'),
        }
    })


urlpatterns = [
    # Административная панель
    path('admin/', admin.site.urls),

    # Health check
    path('health/', health_check, name='health-check'),

    # API корневой endpoint
    path('api/', api_root, name='api-root'),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Основные API маршруты
    path('api/auth/', include('users.urls')),
    path('api/products/', include('products.urls')),
    path('api/stores/', include('stores.urls')),
    path('api/orders/', include('orders.urls')),
    path('api/reports/', include('reports.urls')),
    # path('api/notifications/', include('notifications.urls')),

    # Дополнительные модули (когда будут готовы)
    # path('api/messaging/', include('messaging.urls')),
    # path('api/tracking/', include('apps.tracking.urls')),
    # path('api/requests/', include('apps.support_requests.urls')),

    # Редирект с корня на API документацию
    path('', RedirectView.as_view(url='/api/docs/', permanent=False), name='root-redirect'),
]

# Обработка статических и медиа файлов
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    # Django Debug Toolbar (только в режиме отладки)
    if 'debug_toolbar' in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
                          path('__debug__/', include(debug_toolbar.urls)),
                      ] + urlpatterns


# Настройка заголовков Admin панели
admin.site.site_header = 'B2B Система - Администрирование'
admin.site.site_title = 'B2B Система'
admin.site.index_title = 'Панель управления'
