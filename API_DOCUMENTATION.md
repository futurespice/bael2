# БайЭл API - Документация для мобильного разработчика

**Базовый URL:** `https://baielapp.com.kg/api/`  
**Версия:** 2.0.0  
**Авторизация:** Bearer Token (JWT)

---

## Оглавление

1. [Аутентификация](#1-аутентификация)
2. [Профиль пользователя](#2-профиль-пользователя)
3. [Магазины](#3-магазины)
4. [Товары](#4-товары)
5. [Заказы](#5-заказы)
6. [Отчёты и статистика](#6-отчёты-и-статистика)

---

## 1. Аутентификация

### 1.1 Регистрация
```
POST /api/auth/register/
```

**Request Body:**
```json
{
  "name": "Азат",
  "second_name": "Мурзаев",
  "email": "azat@example.com",
  "phone": "+996555123456",
  "password": "p!8Rt123456"
}
```

**Response 201:**
```json
{
  "user": {
    "id": 1,
    "phone": "+996555123456",
    "email": "azat@example.com",
    "name": "Азат",
    "second_name": "Мурзаев",
    "full_name": "Азат Мурзаев",
    "role": "store",
    "approval_status": "approved"
  },
  "tokens": {
    "access": "eyJ0eXAiOiJKV1...",
    "refresh": "eyJ0eXAiOiJKV1..."
  }
}
```

**Валидация:**
- `phone`: формат `+996XXXXXXXXX` (13 символов)
- `email`: до 50 символов, уникальный
- `name`, `second_name`: 2-24 символа
- `password`: минимум 6 символов (+ маркер `p!8Rt` для партнёров)

---

### 1.2 Вход
```
POST /api/auth/login/
```

**Request Body:**
```json
{
  "phone": "+996555123456",
  "password": "p!8Rt123456",
  "remember_me": true
}
```

**Response 200:**
```json
{
  "access": "eyJ0eXAiOiJKV1...",
  "refresh": "eyJ0eXAiOiJKV1...",
  "user": {
    "id": 1,
    "phone": "+996555123456",
    "email": "azat@example.com",
    "full_name": "Азат Мурзаев",
    "role": "store",
    "approval_status": "approved",
    "is_active": true
  }
}
```

**Роли:**
- `store` - Магазин (обычный пользователь)
- `partner` - Партнёр (регистрация с маркером `p!8Rt` в пароле)
- `admin` - Администратор

---

### 1.3 Выход
```
POST /api/auth/logout/
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "refresh": "eyJ0eXAiOiJKV1..."
}
```

**Response 200:**
```json
{
  "detail": "Успешный выход"
}
```

---

### 1.4 Обновление токена
```
POST /api/auth/refresh/
```

**Request Body:**
```json
{
  "refresh": "eyJ0eXAiOiJKV1..."
}
```

**Response 200:**
```json
{
  "access": "eyJ0eXAiOiJKV1...(новый)"
}
```

---

### 1.5 Сброс пароля (3 этапа)

**Этап 1: Запрос кода**
```
POST /api/auth/password/reset/
```

**Request Body:**
```json
{
  "email": "azat@example.com"
}
```

**Response 200:**
```json
{
  "message": "Код отправлен на email"
}
```

---

**Этап 2: Проверка кода**
```
POST /api/auth/password/verify/
```

**Request Body:**
```json
{
  "email": "azat@example.com",
  "code": "12345"
}
```

**Response 200:**
```json
{
  "message": "Код верный",
  "token": "reset_token_abc123"
}
```

---

**Этап 3: Установка нового пароля**
```
POST /api/auth/password/confirm/
```

**Request Body:**
```json
{
  "email": "azat@example.com",
  "code": "12345",
  "new_password": "новыйПароль123"
}
```

**Response 200:**
```json
{
  "message": "Пароль успешно изменён"
}
```

---

## 2. Профиль пользователя

### 2.1 Получить профиль
```
GET /api/auth/profile/
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "id": 1,
  "email": "azat@example.com",
  "phone": "+996555123456",
  "name": "Азат",
  "second_name": "Мурзаев",
  "full_name": "Азат Мурзаев",
  "role": "store",
  "approval_status": "approved",
  "is_active": true,
  "avatar": "/media/avatars/user_1.jpg",
  "created_at": "2026-01-15T10:00:00Z",
  "last_login": "2026-01-29T08:30:00Z"
}
```

---

### 2.2 Обновить профиль
```
PATCH /api/auth/profile/
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

**Request Body:**
```json
{
  "name": "Азат",
  "second_name": "Мурзаев",
  "email": "new_email@example.com",
  "avatar": "<file>"
}
```

**Response 200:** _Аналогичен GET profile_

---

## 3. Магазины

### 3.1 Список регионов
```
GET /api/stores/regions/
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "count": 7,
  "results": [
    {
      "id": 1,
      "name": "Чуйская область",
      "cities_count": 5,
      "stores_count": 120
    }
  ]
}
```

---

### 3.2 Список городов
```
GET /api/stores/cities/
GET /api/stores/cities/?region=1
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "count": 25,
  "results": [
    {
      "id": 1,
      "name": "Бишкек",
      "region": 1,
      "region_name": "Чуйская область",
      "stores_count": 50
    }
  ]
}
```

---

### 3.3 Создать магазин
```
POST /api/stores/stores/
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "name": "ООО Супермаркет",
  "inn": "123456789012",
  "owner_name": "Иванов Иван Иванович",
  "phone": "+996555111222",
  "region": 1,
  "city": 1,
  "address": "ул. Киевская, д. 15"
}
```

**Response 201:**
```json
{
  "id": 1,
  "name": "ООО Супермаркет",
  "inn": "123456789012",
  "owner": 5,
  "owner_name": "Иванов Иван Иванович",
  "phone": "+996555111222",
  "region": 1,
  "region_name": "Чуйская область",
  "city": 1,
  "city_name": "Бишкек",
  "address": "ул. Киевская, д. 15",
  "debt": "0.00",
  "total_paid": "0.00",
  "approval_status": "approved",
  "is_active": true,
  "created_at": "2026-01-29T10:00:00Z"
}
```

**Валидация:**
- `inn`: 12-14 цифр, уникальный
- `phone`: формат `+996XXXXXXXXX`

---

### 3.4 Список магазинов
```
GET /api/stores/stores/
GET /api/stores/stores/?city=1&search=супер
Authorization: Bearer <access_token>
```

**Query параметры:**
- `city` - ID города
- `region` - ID региона
- `search` - Поиск по названию/ИНН/владельцу
- `is_active` - true/false

**Response 200:**
```json
{
  "count": 50,
  "next": "/api/stores/stores/?page=2",
  "results": [
    {
      "id": 1,
      "name": "ООО Супермаркет",
      "inn": "123456789012",
      "owner_name": "Иванов И.И.",
      "phone": "+996555111222",
      "city_name": "Бишкек",
      "region_name": "Чуйская область",
      "debt": "15000.00",
      "is_active": true
    }
  ]
}
```

---

### 3.5 Детали магазина
```
GET /api/stores/stores/{id}/
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "id": 1,
  "name": "ООО Супермаркет",
  "inn": "123456789012",
  "owner": 5,
  "owner_name": "Иванов Иван Иванович",
  "phone": "+996555111222",
  "region": 1,
  "region_name": "Чуйская область",
  "city": 1,
  "city_name": "Бишкек",
  "address": "ул. Киевская, д. 15",
  "latitude": 42.8746,
  "longitude": 74.5698,
  "debt": "15000.00",
  "total_paid": "250000.00",
  "approval_status": "approved",
  "approval_status_display": "Одобрен",
  "is_active": true,
  "total_orders_count": 45,
  "accepted_orders_count": 40,
  "inventory_items_count": 25,
  "users_count": 2,
  "created_at": "2026-01-15T10:00:00Z"
}
```

---

### 3.6 Выбрать магазин (для role='store')
```
POST /api/stores/select/
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "store_id": 1
}
```

**Response 200:**
```json
{
  "message": "Магазин выбран",
  "store": {
    "id": 1,
    "name": "ООО Супермаркет",
    "inn": "123456789012"
  }
}
```

---

### 3.7 Отменить выбор магазина
```
POST /api/stores/deselect/
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "message": "Выбор магазина отменён"
}
```

---

## 4. Товары

### 4.1 Каталог товаров
```
GET /api/products/products/
GET /api/products/products/?search=мука&is_active=true
Authorization: Bearer <access_token>
```

**Query параметры:**
- `search` - Поиск по названию
- `is_active` - true/false
- `is_bonus` - true/false (бонусные товары)
- `ordering` - `name`, `-name`, `final_price`, `-final_price`

**Response 200:**
```json
{
  "count": 100,
  "results": [
    {
      "id": 1,
      "name": "Мука пшеничная 1 сорт",
      "description": "Мука высшего качества",
      "unit": "kg",
      "unit_display": "кг",
      "is_weight_based": true,
      "is_bonus": false,
      "final_price": "85.00",
      "price_per_100g": "8.50",
      "stock_quantity": "500.000",
      "is_active": true,
      "is_available": true,
      "images": [
        {
          "id": 1,
          "image": "/media/products/muka.jpg",
          "order": 0
        }
      ]
    },
    {
      "id": 2,
      "name": "Самса с мясом",
      "unit": "piece",
      "unit_display": "шт",
      "is_weight_based": false,
      "is_bonus": true,
      "final_price": "45.00",
      "stock_quantity": "200.000",
      "is_active": true,
      "images": []
    }
  ]
}
```

---

### 4.2 Детали товара
```
GET /api/products/products/{id}/
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "id": 1,
  "name": "Мука пшеничная 1 сорт",
  "description": "Мука высшего качества для выпечки",
  "unit": "kg",
  "unit_display": "кг",
  "is_weight_based": true,
  "is_bonus": false,
  "average_cost_price": "60.00",
  "markup_percentage": "40.00",
  "manual_price": null,
  "final_price": "85.00",
  "price_per_100g": "8.50",
  "profit": "25.00",
  "stock_quantity": "500.000",
  "is_active": true,
  "is_available": true,
  "popularity_weight": 100,
  "images_read": [
    {
      "id": 1,
      "image": "/media/products/muka.jpg",
      "order": 0
    }
  ],
  "recipe_items": [],
  "created_at": "2026-01-10T10:00:00Z"
}
```

---

## 5. Заказы

### 5.1 Создать заказ (Магазин)
```
POST /api/orders/store-orders/
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "items": [
    {
      "product": 1,
      "quantity": 10.5
    },
    {
      "product": 2,
      "quantity": 50
    }
  ]
}
```

**Response 201:**
```json
{
  "id": 1,
  "store": 1,
  "store_name": "ООО Супермаркет",
  "status": "pending",
  "status_display": "Ожидает",
  "order_type": "preorder",
  "total_amount": "3142.50",
  "items": [
    {
      "id": 1,
      "product": 1,
      "product_name": "Мука пшеничная",
      "quantity": "10.500",
      "quantity_display": "10.5 кг",
      "price": "85.00",
      "total": "892.50",
      "is_bonus": false
    },
    {
      "id": 2,
      "product": 2,
      "product_name": "Самса с мясом",
      "quantity": "50.000",
      "quantity_display": "50 шт",
      "price": "45.00",
      "total": "2250.00",
      "is_bonus": true,
      "bonus_percent": 4.76
    }
  ],
  "created_at": "2026-01-29T10:00:00Z"
}
```

---

### 5.2 Мои заказы (Магазин)
```
GET /api/orders/store-orders/my-orders/
GET /api/orders/store-orders/my-orders/?status=pending
Authorization: Bearer <access_token>
```

**Query параметры:**
- `status` - `pending`, `in_transit`, `accepted`, `rejected`
- `start_date` - YYYY-MM-DD
- `end_date` - YYYY-MM-DD

**Response 200:**
```json
{
  "count": 15,
  "results": [
    {
      "id": 1,
      "store": 1,
      "store_name": "ООО Супермаркет",
      "owner_name": "Иванов И.И.",
      "store_phone": "+996555111222",
      "status": "in_transit",
      "status_display": "В пути",
      "order_type": "preorder",
      "total_amount": "3142.50",
      "items_summary": "Запрос на 50 шт 10.5 кг",
      "items_count": 2,
      "created_at": "2026-01-29T10:00:00Z"
    }
  ]
}
```

---

### 5.3 Детали заказа (Магазин)
```
GET /api/orders/store-orders/my-orders/{order_id}/
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "id": 1,
  "store": 1,
  "store_name": "ООО Супермаркет",
  "owner_name": "Иванов Иван Иванович",
  "store_phone": "+996555111222",
  "status": "in_transit",
  "status_display": "В пути",
  "order_type": "preorder",
  "total_amount": "3142.50",
  "debt_amount": "3142.50",
  "paid_amount": "0.00",
  "partner_name": "Асанов Асан",
  "items": [
    {
      "id": 1,
      "product": 1,
      "product_name": "Мука пшеничная",
      "is_weight_based": true,
      "quantity": "10.500",
      "quantity_display": "10.5 кг",
      "price": "85.00",
      "total": "892.50",
      "is_bonus": false
    }
  ],
  "created_at": "2026-01-29T10:00:00Z"
}
```

---

### 5.4 Список заказов (Админ)
```
GET /api/orders/store-orders/
GET /api/orders/store-orders/?status=pending
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "count": 50,
  "results": [
    {
      "id": 1,
      "store": 1,
      "store_name": "ООО Супермаркет",
      "owner_name": "Иванов И.И.",
      "store_phone": "+996555111222",
      "status": "pending",
      "status_display": "Ожидает",
      "order_type": "preorder",
      "total_amount": "3142.50",
      "items_summary": "Запрос на 50 шт 10.5 кг",
      "piece_count": 50,
      "weight_total": "10.5",
      "items_count": 2,
      "created_at": "2026-01-29T10:00:00Z"
    }
  ]
}
```

---

### 5.5 Одобрить заказ (Админ)
```
POST /api/orders/store-orders/{id}/approve/
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "partner": 5
}
```

**Response 200:**
```json
{
  "message": "Заказ одобрен",
  "order": {
    "id": 1,
    "status": "in_transit",
    "partner": 5,
    "partner_name": "Асанов Асан"
  }
}
```

---

### 5.6 Отклонить заказ (Админ)
```
POST /api/orders/store-orders/{id}/reject/
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "reason": "Товар закончился на складе"
}
```

**Response 200:**
```json
{
  "message": "Заказ отклонён",
  "order": {
    "id": 1,
    "status": "rejected",
    "reject_reason": "Товар закончился на складе"
  }
}
```

---

### 5.7 Подтвердить доставку (Партнёр)
```
POST /api/orders/partner-requests/{id}/confirm/
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "confirmed_items": [
    {
      "item_id": 1,
      "delivered_quantity": 10.0
    },
    {
      "item_id": 2,
      "delivered_quantity": 48
    }
  ]
}
```

**Response 200:**
```json
{
  "message": "Заказ подтверждён",
  "order": {
    "id": 1,
    "status": "accepted",
    "total_amount": "3052.50",
    "debt_amount": "3052.50"
  }
}
```

---

### 5.8 Создать ручной заказ (Партнёр)
```
POST /api/orders/partners/manual-orders/
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "store": 1,
  "items": [
    {
      "product": 1,
      "quantity": 5.0,
      "price": 85.00
    }
  ]
}
```

**Response 201:**
```json
{
  "id": 2,
  "store": 1,
  "store_name": "ООО Супермаркет",
  "order_type": "manual",
  "status": "accepted",
  "total_amount": "425.00",
  "items": [
    {
      "product": 1,
      "product_name": "Мука пшеничная",
      "quantity": "5.000",
      "price": "85.00",
      "total": "425.00"
    }
  ],
  "created_at": "2026-01-29T11:00:00Z"
}
```

---

## 6. Отчёты и статистика

### 6.1 Общая статистика (Админ)
```
GET /api/reports/statistics/
GET /api/reports/statistics/?period=month&store_id=1
Authorization: Bearer <access_token>
```

**Query параметры:**
- `period`: `day`, `week`, `month`, `half_year`, `year`, `all_time`
- `start_date`, `end_date`: YYYY-MM-DD
- `store_id`, `partner_id`, `region_id`, `city_id`

**Response 200:**
```json
{
  "period": "month",
  "total_orders": 150,
  "total_revenue": "1250000.00",
  "total_debt": "350000.00",
  "total_paid": "900000.00",
  "orders_by_status": {
    "pending": 10,
    "in_transit": 25,
    "accepted": 110,
    "rejected": 5
  },
  "top_products": [
    {
      "product_id": 1,
      "product_name": "Мука пшеничная",
      "total_quantity": "500.00",
      "total_revenue": "42500.00"
    }
  ]
}
```

---

### 6.2 История магазина
```
GET /api/reports/store-history/{store_id}/
GET /api/reports/store-history/1/?start_date=2026-01-01
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "store": {
    "id": 1,
    "name": "ООО Супермаркет"
  },
  "period": {
    "start": "2026-01-01",
    "end": "2026-01-29"
  },
  "total_orders": 15,
  "total_amount": "125000.00",
  "total_debt": "25000.00",
  "total_paid": "100000.00",
  "orders": [
    {
      "id": 1,
      "status": "accepted",
      "total_amount": "3142.50",
      "created_at": "2026-01-29T10:00:00Z"
    }
  ]
}
```

---

### 6.3 Статистика партнёра
```
GET /api/reports/partners/statistics/
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "partner": {
    "id": 5,
    "name": "Асанов Асан"
  },
  "total_orders_delivered": 45,
  "total_revenue": "850000.00",
  "total_collected": "750000.00",
  "pending_collection": "100000.00",
  "current_inventory_value": "50000.00"
}
```

---

### 6.4 Профиль партнёра
```
GET /api/reports/partners/profile/
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "id": 5,
  "name": "Асанов Асан",
  "phone": "+996555000111",
  "email": "asanov@example.com",
  "total_orders": 45,
  "active_orders": 3,
  "stores_served": 15,
  "inventory_items_count": 20
}
```

---

### 6.5 Трекер партнёра (заказы)
```
GET /api/reports/partners/tracker/
GET /api/reports/partners/tracker/?type=preorder
Authorization: Bearer <access_token>
```

**Query параметры:**
- `type`: `all`, `preorder`, `manual`

**Response 200:**
```json
{
  "count": 25,
  "results": [
    {
      "id": 1,
      "store": 1,
      "store_name": "ООО Супермаркет",
      "status": "accepted",
      "order_type": "preorder",
      "total_amount": "3142.50",
      "debt_amount": "3142.50",
      "items_count": 2,
      "created_at": "2026-01-29T10:00:00Z"
    }
  ]
}
```

---

## Инвентарь партнёра

### Получить инвентарь
```
GET /api/stores/partner-inventory/
GET /api/stores/partner-inventory/?has_stock=true
Authorization: Bearer <access_token>
```

**Response 200:**
```json
{
  "count": 20,
  "results": [
    {
      "id": 1,
      "product": 1,
      "product_name": "Мука пшеничная",
      "quantity": "50.000",
      "unit": "kg",
      "unit_display": "кг",
      "is_weight_based": true,
      "last_updated": "2026-01-29T08:00:00Z"
    }
  ]
}
```

---

## Коды ошибок

| Код | Описание |
|-----|----------|
| 400 | Неверный запрос (ошибка валидации) |
| 401 | Не авторизован (невалидный/истёкший токен) |
| 403 | Доступ запрещён (недостаточно прав) |
| 404 | Ресурс не найден |
| 500 | Внутренняя ошибка сервера |

**Пример ошибки валидации (400):**
```json
{
  "phone": ["Пользователь с таким номером уже существует"],
  "email": ["Email не должен превышать 50 символов"]
}
```

**Пример ошибки авторизации (401):**
```json
{
  "detail": "Given token not valid for any token type",
  "code": "token_not_valid"
}
```

---

## Заголовки запросов

```
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: application/json
```

Для загрузки файлов (аватар, изображения):
```
Content-Type: multipart/form-data
```

---

## Пагинация

Все списочные эндпоинты возвращают пагинированные результаты:

```json
{
  "count": 100,
  "next": "https://baielapp.com.kg/api/products/products/?page=2",
  "previous": null,
  "results": [...]
}
```

**Query параметры:**
- `page` - номер страницы (по умолчанию: 1)
- `page_size` - размер страницы (по умолчанию: 20, макс: 100)
