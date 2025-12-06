# apps/orders/throttles.py - НОВЫЙ ФАЙЛ v2.0
"""
Throttle классы для защиты эндпоинтов заказов.

СРЕДНЯЯ проблема #25: Rate Limiting
"""

from rest_framework.throttling import UserRateThrottle


class OrderCreationThrottle(UserRateThrottle):
    """
    Throttle для создания заказов.
    
    Защита от дублирования заказов и спама.
    30 заказов в час для одного пользователя.
    """
    scope = 'order_creation'
    rate = '30/hour'


class DebtPaymentThrottle(UserRateThrottle):
    """
    Throttle для погашения долгов.
    
    Защита от ошибочных множественных платежей.
    20 платежей в час для одного пользователя.
    """
    scope = 'debt_payment'
    rate = '20/hour'


class DefectReportThrottle(UserRateThrottle):
    """
    Throttle для отчётов о браке.
    
    Защита от спама отчётами о браке.
    10 отчётов в час для одного пользователя.
    """
    scope = 'defect_report'
    rate = '10/hour'
