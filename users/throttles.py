# apps/users/throttles.py - НОВЫЙ ФАЙЛ v2.0
"""
Custom throttle классы для защиты критических эндпоинтов.

СРЕДНЯЯ проблема #25: Rate Limiting

ИСПОЛЬЗОВАНИЕ:
- LoginThrottle: 5 попыток в минуту (защита от brute-force)
- PasswordResetThrottle: 3 запроса в час (защита от спама)
- RegistrationThrottle: 10 регистраций в час с одного IP
"""

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginThrottle(AnonRateThrottle):
    """
    Throttle для эндпоинта логина.
    
    Защита от brute-force атак.
    5 попыток в минуту с одного IP.
    """
    scope = 'login'
    rate = '5/minute'


class PasswordResetThrottle(AnonRateThrottle):
    """
    Throttle для эндпоинта сброса пароля.
    
    Защита от спама email.
    3 запроса в час с одного IP.
    """
    scope = 'password_reset'
    rate = '3/hour'


class RegistrationThrottle(AnonRateThrottle):
    """
    Throttle для эндпоинта регистрации.
    
    Защита от массовой регистрации ботов.
    10 регистраций в час с одного IP.
    """
    scope = 'registration'
    rate = '10/hour'


class OrderCreationThrottle(UserRateThrottle):
    """
    Throttle для создания заказов.
    
    Защита от дублирования заказов.
    30 заказов в час для одного пользователя.
    """
    scope = 'order_creation'
    rate = '30/hour'


class BurstThrottle(UserRateThrottle):
    """
    Throttle для защиты от burst-атак.
    
    Ограничение: 60 запросов в минуту.
    """
    scope = 'burst'
    rate = '60/minute'
