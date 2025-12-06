"""
URL configuration for БайЭл project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from django.views.generic import RedirectView
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import connection
from django.core.cache import cache


@require_http_methods(["GET"])
def health_check(request):
    """Health check endpoint для мониторинга и load balancer"""
    health_status = {
        'status': 'healthy',
        'service': 'БайЭл API',
        'version': '2.0.0',
        'checks': {}
    }
    
    # Проверка базы данных
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_status['checks']['database'] = 'ok'
    except Exception as e:
        health_status['checks']['database'] = f'error: {str(e)}'
        health_status['status'] = 'unhealthy'
    
    # Проверка Redis
    try:
        cache.set('health_check', 'ok', timeout=10)
        if cache.get('health_check') == 'ok':
            health_status['checks']['redis'] = 'ok'
        else:
            health_status['checks']['redis'] = 'error: cache not working'
            health_status['status'] = 'unhealthy'
    except Exception as e:
        health_status['checks']['redis'] = f'error: {str(e)}'
        health_status['status'] = 'unhealthy'
    
    status_code = 200 if health_status['status'] == 'healthy' else 503
    return JsonResponse(health_status, status=status_code)


@require_http_methods(["GET"])
def api_root(request):
    """Корневой endpoint API с документацией"""
    base_url = request.build_absolute_uri('/api/')
    return JsonResponse({
        'message': 'БайЭл - B2B платформа для дистрибуции',
        'version': '2.0.0',
        'documentation': {
            'swagger': f'{base_url}docs/',
            'redoc': f'{base_url}redoc/',
            'schema': f'{base_url}schema/',
        },
        'endpoints': {
            'auth': f'{base_url}auth/',
            'products': f'{base_url}products/',
            'stores': f'{base_url}stores/',
            'orders': f'{base_url}orders/',
            'reports': f'{base_url}reports/',
        }
    })


urlpatterns = [
    # Health check (для мониторинга)
    path('health/', health_check, name='health-check'),

    # Административная панель
    path('admin/', admin.site.urls),

    # API корневой endpoint
    path('api/', api_root, name='api-root'),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Основные API маршруты (убрал дублирование users)
    path('api/auth/', include('users.urls', namespace='auth')),
    path('api/products/', include('products.urls')),
    path('api/stores/', include('stores.urls')),
    path('api/orders/', include('orders.urls')),
    path('api/reports/', include('reports.urls')),
    # path('api/notifications/', include('notifications.urls')),

    # Редирект с корня на API документацию
    path('', RedirectView.as_view(url='/api/docs/', permanent=False), name='root-redirect'),
]

# Статика и медиа только в DEBUG режиме
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Настройка Admin панели
admin.site.site_header = 'БайЭл - Администрирование'
admin.site.site_title = 'БайЭл'
admin.site.index_title = 'Панель управления'
