# ТЕСТОВЫЕ ДАННЫЕ БАЙЭЛ — ПОЛНОЕ РУКОВОДСТВО (A → Z)

> Последнее обновление: 2026-03-03
> Версия приложения: 3.0+

---

## СОДЕРЖАНИЕ

1. [Пользователи и учётные данные](#1-пользователи)
2. [География (регионы, города)](#2-география)
3. [Магазины](#3-магазины)
4. [Расходы (Expense)](#4-расходы)
5. [Товары (Product)](#5-товары)
6. [Рецепты товаров (ProductRecipe)](#6-рецепты-товаров)
7. [Партии производства (ProductionBatch)](#7-партии-производства)
8. [Инвентарь партнёра (PartnerInventory)](#8-инвентарь-партнёра)
9. [Заказы магазина — полный цикл](#9-заказы-магазина)
10. [Дефекты (DefectiveProduct)](#10-дефекты)
11. [Возвраты (ReturnedItem)](#11-возвраты)
12. [Оплата долга (DebtPayment)](#12-оплата-долга)
13. [Расходы партнёра (PartnerExpense)](#13-расходы-партнёра)
14. [Сброс пароля](#14-сброс-пароля)
15. [FCM-токены и уведомления](#15-fcm-и-уведомления)
16. [Граничные и негативные сценарии](#16-граничные-сценарии)
17. [Порядок запуска тестов](#17-порядок-запуска)

---

## 1. ПОЛЬЗОВАТЕЛИ

### 1.1 Учётные данные

| Роль      | Телефон          | Email                 | Пароль      | Флаги                  |
|-----------|------------------|-----------------------|-------------|------------------------|
| **Admin** | +996700000001    | admin@test.local      | admin123    | is_staff=True, is_superuser=True |
| **Partner** | +996700000002  | partner@test.local    | partner123  | role=partner           |
| **Store** | +996700000003    | store@test.local      | store123    | role=store             |
| **Store2** | +996700000004   | store2@test.local     | store2_pw   | role=store (второй пользователь) |
| **Partner2** | +996700000005 | partner2@test.local   | partner2_pw | role=partner (второй партнёр) |

### 1.2 Дополнительные поля пользователя

```
name       = 'Айбек'           # first name
second_name = 'Мамытов'        # last name / фамилия
avatar     = null              # опциональное изображение
approval_status = 'approved'   # admin, partner автоматически approved
```

### 1.3 Правила валидации

- Телефон: строго `+996XXXXXXXXX` (13 символов)
- Email: уникальный, не более 50 символов
- Пароль: минимум 8 символов (Django default)

---

## 2. ГЕОГРАФИЯ

### 2.1 Регионы (Region)

| ID | Название               |
|----|------------------------|
| 1  | Чуйская область        |
| 2  | Ошская область         |
| 3  | Джалал-Абадская область|
| 4  | Иссык-Кульская область |
| 5  | ТЕСТ Регион            |

### 2.2 Города (City)

| Регион                  | Город           |
|-------------------------|-----------------|
| Чуйская область         | Бишкек          |
| Чуйская область         | Токмок          |
| Чуйская область         | Кант            |
| Ошская область          | Ош              |
| Ошская область          | Узген           |
| Джалал-Абадская область | Джалал-Абад     |
| Иссык-Кульская область  | Каракол         |
| ТЕСТ Регион             | ТЕСТ Город      |

> **Важно:** Уникальность города — связка [region, name].

---

## 3. МАГАЗИНЫ

### 3.1 Тестовые магазины

| Поле             | Магазин 1                   | Магазин 2                   |
|------------------|-----------------------------|-----------------------------|
| name             | ТЕСТ Магазин Айсберг        | ТЕСТ Магазин Арктика        |
| owner            | store@test.local            | store2@test.local           |
| region           | ТЕСТ Регион                 | Чуйская область             |
| city             | ТЕСТ Город                  | Бишкек                      |
| address          | ул. Тестовая, 1             | пр. Манаса, 55              |
| inn              | 123456700001                | 123456700002                |
| owner_name       | Магазин ТЕСТ                | Арктика ТЭ                  |
| phone            | +996555111222               | +996555333444               |
| approval_status  | approved                    | approved                    |
| is_active        | True                        | True                        |
| debt             | 0.00                        | 0.00 (начальный)            |

### 3.2 Правила валидации магазина

- INN: 12–14 цифр, уникальный
- Телефон магазина: +996XXXXXXXXX
- При создании — `approval_status='approved'` (автоматически)
- Заморозка: `is_active=False` → нельзя создавать заказы

### 3.3 Выбор магазина пользователем (StoreSelection)

```
POST /api/stores/select/   { "store_id": 1 }
POST /api/stores/deselect/ {}
```

- У одного пользователя одновременно активен только один магазин
- Несколько пользователей могут работать в одном магазине

---

## 4. РАСХОДЫ (Expense)

### 4.1 Физические расходы — Сюзерены (PHYSICAL + SUZERAIN)

> Главные ингредиенты. Количество задаётся вручную в рецепте.

| Название       | unit_type  | price_per_unit | state      | apply_type |
|----------------|------------|----------------|------------|------------|
| Мука пшеничная | per_weight | 50.00 (сом/кг) | mechanical | regular    |
| Фарш говяжий   | per_weight | 400.00         | mechanical | regular    |
| Молоко         | per_volume | 80.00 (сом/л)  | mechanical | regular    |
| Тесто готовое  | per_weight | 120.00         | mechanical | regular    |
| Курятина       | per_weight | 280.00         | mechanical | regular    |

### 4.2 Физические расходы — Обыватели (PHYSICAL + CIVILIAN)

> Зависят от Сюзерена через пропорцию (dependency_ratio).

| Название       | unit_type  | price_per_unit | depends_on_suzerain | dependency_ratio |
|----------------|------------|----------------|---------------------|------------------|
| Лук репчатый   | per_weight | 30.00          | Мука пшеничная      | 0.50 (50% от муки) |
| Соль           | per_weight | 10.00          | Мука пшеничная      | 0.02 (2%)         |
| Специи         | per_weight | 200.00         | Фарш говяжий        | 0.03 (3%)         |
| Упаковка (пакет)| per_piece | 2.00           | Молоко              | 1.00 (1 уп/л)     |

### 4.3 Накладные расходы — Автоматические/Вассалы (OVERHEAD)

> Накладные расходы становятся Вассалами автоматически.
> Имеют `monthly_amount` → `daily_amount = monthly / 30`.

| Название        | state      | apply_type | monthly_amount | daily_amount |
|-----------------|------------|------------|----------------|--------------|
| Аренда склада   | automatic  | universal  | 30 000.00      | 1 000.00     |
| Зарплата персонала | automatic | universal | 60 000.00     | 2 000.00     |
| Топливо         | automatic  | universal  | 15 000.00      | 500.00       |
| Налоги          | mechanical | regular    | 10 000.00      | 333.33       |
| Вода/Коммунальные | automatic | universal | 6 000.00      | 200.00       |

### 4.4 Правила Expense

```
SUZERAIN  = physical + (любой state) + (любой apply_type)
VASSAL    = overhead + mechanical + universal  ← автоматически
CIVILIAN  = physical + зависит от suzerain через depends_on_suzerain
```

- `price_per_unit` обязателен только для PHYSICAL
- `monthly_amount` обязателен для OVERHEAD (automatic)
- Overhead не имеет `unit_type`

---

## 5. ТОВАРЫ (Product)

### 5.1 Штучные товары (is_weight_based=False)

| Название              | unit  | manual_price | stock_qty | is_bonus | markup% |
|-----------------------|-------|--------------|-----------|----------|---------|
| ТЕСТ Мороженое Пломбир| piece | 100.00       | 1000      | **True** | 30%     |
| ТЕСТ Сок Яблочный     | piece | 50.00        | 500       | False    | 25%     |
| ТЕСТ Пельмени 500г    | piece | 180.00       | 300       | True     | 35%     |
| ТЕСТ Кефир 1л         | piece | 75.00        | 400       | False    | 20%     |

> `is_bonus=True` → каждый 21-й бесплатно.
> Формула: `bonus_count = (qty × 2) // 25`

### 5.2 Весовые товары (is_weight_based=True)

| Название                   | unit   | manual_price | stock_qty | is_bonus | markup% |
|----------------------------|--------|--------------|-----------|----------|---------|
| ТЕСТ Сыр Брынза (весовой)  | kg     | 800.00       | 50        | False    | 40%     |
| ТЕСТ Мясо Говядина (весовой)| kg    | 650.00       | 100       | False    | 45%     |
| ТЕСТ Масло сливочное (вес) | kg     | 550.00       | 30        | False    | 30%     |

> Весовые товары продаются кратно 0.1 кг (100 г).
> Цена за 100г = `final_price / 10`.
> Weight required в заказах, quantity необязателен.

### 5.3 Расчёт final_price

```
final_price = average_cost_price × (1 + markup_percentage / 100)
           OR manual_price  ← если manual_price задан и avg_cost = 0
```

---

## 6. РЕЦЕПТЫ ТОВАРОВ (ProductRecipe)

### 6.1 Рецепт: ТЕСТ Пельмени 500г

| Расход              | Тип      | quantity_per_unit | Описание                           |
|---------------------|----------|-------------------|------------------------------------|
| Мука пшеничная      | suzerain | 0.200             | 200г муки на 1 упаковку            |
| Фарш говяжий        | suzerain | 0.300             | 300г фарша на 1 упаковку           |
| Лук репчатый        | civilian | (ratio 0.50)      | 50% от qty муки = 100г             |
| Соль                | civilian | (ratio 0.02)      | 2% от муки = 4г                    |
| Упаковка (пакет)    | civilian | (ratio 1.00)      | 1 упаковка / 1 шт пельменей        |
| Аренда склада       | overhead | —                 | распределяется через ProductionBatch|

### 6.2 Рецепт: ТЕСТ Мороженое Пломбир

| Расход           | Тип      | quantity_per_unit |
|------------------|----------|-------------------|
| Молоко           | suzerain | 0.150             |
| Специи           | civilian | (ratio 0.01)      |
| Упаковка (пакет) | civilian | (ratio 1.00)      |

### 6.3 ProductRecipe поля

```python
ProductRecipe(
    product=<Product>,
    expense=<Expense>,
    quantity_per_unit=Decimal('0.200'),   # для сюзеренов (авто из absolute_qty)
    absolute_quantity=Decimal('40.000'),  # вход: 40 кг муки на N упаковок
    product_quantity=Decimal('200'),      # вход: на 200 штук
    proportion=None,                      # для обывателей (0.0–1.0)
)
```

---

## 7. ПАРТИИ ПРОИЗВОДСТВА (ProductionBatch)

### 7.1 Сценарий A — ввод количества товара

```python
ProductionBatch(
    product=пельмени,
    input_type='from_quantity',
    quantity=Decimal('200'),      # производим 200 упаковок
    # Авто-рассчитывается:
    total_physical_cost=...,      # Мука + Фарш + Лук + ...
    total_overhead_cost=...,      # Аренда + Зарплата / на долю
    cost_per_unit=...,            # (physical + overhead) / 200
)
```

**Ожидаемый расчёт:**
- Мука: 200 упак × 0.2 кг × 50 сом/кг = 2 000
- Фарш: 200 × 0.3 кг × 400 = 24 000
- Лук: (200 × 0.2 кг × 0.50) × 30 = 600
- Соль: (200 × 0.2 кг × 0.02) × 10 = 8
- Physical итого: **26 608**
- Overhead (аренда 1000 + зарплата 2000 + топливо 500): **3 500 / кол-во партий**
- cost_per_unit ≈ 150–160 сом

### 7.2 Сценарий B — ввод объёма сюзерена

```python
ProductionBatch(
    product=пельмени,
    input_type='from_suzerain',
    suzerain_expense=мука,
    suzerain_quantity=Decimal('20.0'),  # есть 20 кг муки
    # Авто-рассчитывается:
    quantity=Decimal('100'),    # 20кг / 0.2кг_на_упак = 100 упаковок
    total_physical_cost=...,
    cost_per_unit=...,
)
```

### 7.3 После создания ProductionBatch

- `Product.average_cost_price` обновляется (среднее последних 3-х партий)
- `Product.final_price` пересчитывается через наценку

---

## 8. ИНВЕНТАРЬ ПАРТНЁРА (PartnerInventory)

### 8.1 Начальные остатки

| Товар                      | quantity | reserved | bonus | is_bonus |
|----------------------------|----------|----------|-------|----------|
| ТЕСТ Мороженое Пломбир     | 100      | 0        | 0     | True     |
| ТЕСТ Сок Яблочный          | 100      | 0        | 0     | False    |
| ТЕСТ Пельмени 500г         | 100      | 0        | 0     | True     |
| ТЕСТ Кефир 1л              | 100      | 0        | 0     | False    |
| ТЕСТ Сыр Брынза (весовой)  | 50       | 0        | 0     | False    |
| ТЕСТ Мясо Говядина (весовой)| 100     | 0        | 0     | False    |
| ТЕСТ Масло сливочное       | 30       | 0        | 0     | False    |

### 8.2 Правило бонуса

```
bonus_count = (total_quantity × 2) // 25

Пример:
  Продали 21 шт мороженого →
  (21 × 2) // 25 = 42 // 25 = 1 бесплатный

  Продали 50 шт →
  (50 × 2) // 25 = 4 бесплатных
```

---

## 9. ЗАКАЗЫ МАГАЗИНА — ПОЛНЫЙ ЦИКЛ

### 9.1 Шаг 1: Создание заказа магазином (PENDING)

```http
POST /api/orders/store-orders/
Authorization: Bearer <store_token>

{
  "order_type": "preorder",
  "store_id": 1,
  "prepayment_amount": "1000.00",
  "items": [
    {"product_id": 1, "quantity": "10"},
    {"product_id": 2, "quantity": "5"},
    {"product_id": 5, "quantity": "2.5", "weight": "2.500"}
  ]
}
```

**Ожидаемый ответ:**
```json
{
  "id": 1,
  "status": "pending",
  "total_amount": "3250.00",
  "prepayment_amount": "1000.00",
  "debt_amount": "2250.00",
  "items": [...]
}
```

**Проверки при создании:**
- `store.can_interact` = True (не заморожен, не отклонён)
- Остатки у партнёра достаточны (включая бонусы)
- Цена берётся снапшотом `product.final_price` → `price_at_request`

### 9.2 Шаг 2: Утверждение заказа (IN_TRANSIT)

```http
POST /api/orders/store-orders/1/approve/
Authorization: Bearer <admin_token>

{
  "partner_id": 2
}
```

**Результат:**
- `status` = `in_transit`
- `reviewed_by` = admin
- `reviewed_at` = now()
- StoreOrder помещается в "корзину" партнёра

### 9.3 Шаг 3: Подтверждение партнёром (ACCEPTED)

```http
POST /api/stores/store-inventory/confirm/
Authorization: Bearer <partner_token>

{
  "store_id": 1
}
```

**Что происходит:**
1. Все IN_TRANSIT заказы магазина → `status=ACCEPTED`
2. Товары → StoreInventory (добавляются к складу магазина)
3. Долг создаётся: `debt_amount = total - prepayment`
4. `confirmed_by` = partner, `confirmed_at` = now()

**Проверки StoreInventory после подтверждения:**

| Товар                  | qty до | qty_in_order | bonus | qty после |
|------------------------|--------|--------------|-------|-----------|
| Мороженое (бонус)      | 0      | 10           | 0     | 10        |
| Сок                    | 0      | 5            | 0     | 5         |
| Сыр (весовой)          | 0      | 2.5          | 0     | 2.5       |

### 9.4 Отклонение заказа (REJECTED)

```http
POST /api/orders/store-orders/1/reject/
Authorization: Bearer <admin_token>

{
  "reason": "Недостаточно товара на складе"
}
```

**Результат:**
- `status` = `rejected`
- Инвентарь не изменяется

### 9.5 Ручной заказ (MANUAL, создаёт партнёр)

```http
POST /api/orders/partners/manual-orders/
Authorization: Bearer <partner_token>

{
  "store_id": 1,
  "items": [
    {"product_id": 3, "quantity": "20"},
    {"product_id": 6, "quantity": "5", "weight": "5.000"}
  ],
  "prepayment_amount": "500.00",
  "notes": "Срочный заказ"
}
```

---

## 10. ДЕФЕКТЫ (DefectiveProduct)

### 10.1 Создание дефекта

```http
POST /api/stores/store-inventory/defect/
Authorization: Bearer <partner_token>

{
  "store_id": 1,
  "product_id": 1,
  "quantity": 2,
  "reason": "Повреждена упаковка"
}
```

### 10.2 Состояния дефекта

| Status   | Описание                          | Долг                        |
|----------|-----------------------------------|-----------------------------|
| PENDING  | Ожидает проверки                  | Не изменяется               |
| APPROVED | Подтверждён администратором       | `debt_amount` уменьшается   |
| REJECTED | Отклонён                          | Не изменяется               |

### 10.3 Расчёт суммы дефекта

```
Штучный товар: total = price × quantity
Весовой товар: total = (price / 10) × (weight / 0.1)
```

### 10.4 Граничный случай

- Если `defect.total > order.outstanding_debt` → уменьшить только до 0
- Долг не может стать отрицательным через дефект

---

## 11. ВОЗВРАТЫ (ReturnedItem)

### 11.1 Создание возврата

```http
POST /api/orders/store-orders/1/return-items/
Authorization: Bearer <partner_token>

{
  "items": [
    {"product_id": 2, "quantity": 3, "reason": "Истёк срок годности"},
    {"product_id": 5, "weight": "1.000", "reason": "Плохое качество"}
  ]
}
```

### 11.2 Расчёт суммы возврата

```
Штучный: total = price_at_return × quantity
Весовой: total = (price_at_return / 10) × (weight / 0.1)
```

---

## 12. ОПЛАТА ДОЛГА (DebtPayment)

### 12.1 Полная оплата

```http
POST /api/orders/store-orders/1/pay-debt/
Authorization: Bearer <partner_token>

{
  "amount": "2250.00",
  "comment": "Полная оплата наличными"
}
```

### 12.2 Частичная оплата

```http
POST /api/orders/store-orders/1/pay-debt/
{
  "amount": "1000.00",
  "comment": "Аванс"
}
```

**После оплаты:**
```
paid_amount   += 1000
outstanding_debt = debt_amount - paid_amount
```

### 12.3 Проверки

- `amount > 0` обязательно
- `amount` не должен превышать `outstanding_debt`
- При переплате `store.debt` становится отрицательным

### 12.4 История платежей

```
DebtPayment 1: 1000.00 (аванс)
DebtPayment 2: 500.00  (частичная)
DebtPayment 3: 750.00  (остаток)
Итого paid_amount: 2250.00 = debt_amount → долг закрыт
```

---

## 13. РАСХОДЫ ПАРТНЁРА (PartnerExpense)

### 13.1 Создание расхода

```http
POST /api/products/partner-expenses/
Authorization: Bearer <partner_token>

{
  "amount": "5000.00",
  "description": "Заправка автомобиля",
  "date": "2026-03-03"
}
```

### 13.2 Тестовые записи расходов

| Дата       | Сумма   | Описание               |
|------------|---------|------------------------|
| 2026-02-01 | 3500.00 | Аренда склада (февраль)|
| 2026-02-15 | 1200.00 | Топливо                |
| 2026-03-01 | 3500.00 | Аренда склада (март)   |
| 2026-03-03 | 800.00  | Вода и коммунальные    |

---

## 14. СБРОС ПАРОЛЯ

### 14.1 Трёхэтапный процесс

**Этап 1 — запрос кода:**
```http
POST /api/auth/password/reset/
{
  "phone": "+996700000003"
}
```

**Этап 2 — проверка кода (5-значный):**
```http
POST /api/auth/password/verify/
{
  "phone": "+996700000003",
  "code": "12345"
}
```

**Этап 3 — новый пароль:**
```http
POST /api/auth/password/confirm/
{
  "phone": "+996700000003",
  "code": "12345",
  "new_password": "newpassword123"
}
```

### 14.2 Проверки

- Код действует ограниченное время (expiry)
- `is_used=True` после использования → нельзя использовать повторно
- Неверный код → 400 Bad Request
- Код не того телефона → 400 Bad Request

---

## 15. FCM И УВЕДОМЛЕНИЯ

### 15.1 Регистрация FCM-токена

```http
POST /api/notifications/fcm-token/
Authorization: Bearer <store_token>

{
  "token": "fcm_token_test_12345",
  "device_type": "android"
}
```

### 15.2 Типы уведомлений

| Type                    | Когда отправляется                    |
|-------------------------|---------------------------------------|
| ORDER_STATUS_CHANGED    | При смене статуса заказа              |
| NEW_ORDER               | Новый заказ магазина (для партнёра)   |
| NEW_STORE               | Новый магазин (для admin)             |
| ORDER_ARRIVED           | Партнёр подтвердил (для магазина)     |
| EXPENSE_ADDED           | Добавлен расход (для admin)           |

### 15.3 Прочтение уведомления

```http
PATCH /api/notifications/{id}/read/
Authorization: Bearer <token>
```

---

## 16. ГРАНИЧНЫЕ И НЕГАТИВНЫЕ СЦЕНАРИИ

### 16.1 Аутентификация

| Сценарий                         | Ожидаемый результат      |
|----------------------------------|--------------------------|
| Неверный телефон формат          | 400 Validation Error     |
| Неверный пароль                  | 401 Unauthorized         |
| Просроченный токен               | 401 Token Expired        |
| Запрос без токена                | 401 Unauthorized         |
| Store пытается вызвать admin API | 403 Forbidden            |
| Partner пытается вызвать admin API| 403 Forbidden           |

### 16.2 Создание заказа

| Сценарий                                   | Ожидаемый результат             |
|--------------------------------------------|---------------------------------|
| Заказ без выбранного магазина              | 400 "Магазин не выбран"         |
| Заказ с заморозкой магазина                | 400 "Магазин заморожен"         |
| Количество > остатков у партнёра           | 400 "Недостаточно товара"       |
| Весовой товар без weight                   | 400 "Вес обязателен"            |
| Штучный товар с weight                     | 400 "Вес запрещён"              |
| Пустой список items                        | 400 Validation Error            |
| Повторный заказ (idempotency_key)          | 200 Возврат существующего заказа|

### 16.3 Оплата долга

| Сценарий                          | Ожидаемый результат          |
|-----------------------------------|------------------------------|
| Оплата > outstanding_debt         | 400 "Сумма превышает долг"   |
| Оплата 0 или отрицательная        | 400 Validation Error         |
| Оплата уже закрытого долга        | 400 "Долг уже оплачен"       |

### 16.4 Расходы (Expense)

| Сценарий                                    | Ожидаемый результат     |
|---------------------------------------------|-------------------------|
| Physical без price_per_unit                 | 400 Validation Error    |
| Physical без unit_type                      | 400 Validation Error    |
| Overhead с unit_type                        | 400 "Не применимо"      |
| Civilian без depends_on_suzerain            | 400 Validation Error    |
| dependency_ratio < 0 или > 1               | 400 Validation Error    |

### 16.5 Магазин

| Сценарий                           | Ожидаемый результат             |
|------------------------------------|---------------------------------|
| Дублирующийся INN                  | 400 "INN уже существует"        |
| INN меньше 12 цифр                 | 400 Validation Error            |
| INN больше 14 цифр                 | 400 Validation Error            |
| Несуществующий город               | 400 "Город не найден"           |

### 16.6 Дефект сверх долга

```
outstanding_debt = 500.00
Дефект на сумму = 700.00
Ожидание: долг уменьшается до 0, не до -200
```

---

## 17. ПОРЯДОК ЗАПУСКА ТЕСТОВ

### 17.1 Установка окружения

```bash
cd /Users/azatmurzaev/PycharmProjects/bael2
export FORCE_SQLITE=True
export DJANGO_SETTINGS_MODULE=config.settings
```

### 17.2 Запуск всех тестов

```bash
# Все тесты через pytest
.venv/bin/python -m pytest -v

# С покрытием
.venv/bin/python -m pytest -v --cov=. --cov-report=html

# Конкретный модуль
.venv/bin/python -m pytest products/tests.py -v
.venv/bin/python -m pytest orders/tests.py -v
.venv/bin/python -m pytest stores/tests.py -v
.venv/bin/python -m pytest users/tests.py -v
.venv/bin/python -m pytest reports/tests.py -v
```

### 17.3 Запуск полносистемных тестов

```bash
.venv/bin/python test_complete_system.py
.venv/bin/python test_full_system.py
```

### 17.4 Полный порядок тестирования (A→Z)

```
A. Аутентификация
   - Регистрация (admin/partner/store)
   - Логин — получить access + refresh токены
   - Обновление токена (refresh)
   - Профиль пользователя (GET/PATCH)
   - Сброс пароля (3 этапа)
   - Логаут

B. География
   - Список регионов (GET /api/stores/regions/)
   - Список городов (GET /api/stores/cities/?region=1)

C. Магазины
   - Создание магазина (POST /api/stores/stores/)
   - Просмотр списка (GET /api/stores/stores/)
   - Просмотр одного (GET /api/stores/stores/1/)
   - Выбор магазина пользователем (POST /api/stores/select/)
   - Заморозка магазина (admin PATCH)
   - Размораживание (admin PATCH)

D. Расходы (только admin создаёт)
   - Создать Physical Suzerain (Мука, Фарш)
   - Создать Physical Civilian (Лук — зависит от Муки)
   - Создать Overhead Automatic Universal (Аренда)
   - Список расходов (GET /api/products/expenses/)
   - Редактирование цены расхода

E. Товары
   - Просмотр каталога (GET /api/products/products/)
   - Просмотр одного товара (GET /api/products/products/1/)
   - Изображения товара (до 3 шт)
   - Фильтрация: is_available, is_bonus, is_weight_based

F. Рецепты (ProductRecipe)
   - Создать рецепт для пельменей
   - Просмотр рецепта

G. Партии производства (ProductionBatch)
   - Сценарий A: от количества
   - Сценарий B: от сюзерена
   - Проверить обновление average_cost_price
   - Проверить новую final_price

H. Заказ — Пре-заказ (Preorder)
   - Создание (POST, store)
   - Просмотр своих заказов (GET my-orders/)
   - Утверждение (POST approve/, admin)
   - Отклонение (POST reject/, admin) — альтернативная ветка
   - Подтверждение партнёром (POST confirm/)

I. Инвентарь магазина после подтверждения
   - GET /api/stores/store-inventory/{store_id}/
   - Проверить количество, бонус_count

J. Заказ — Ручной (Manual, создаёт партнёр)
   - Создание (POST manual-orders/, partner)
   - Подтверждение (корзина уже есть → confirm)

K. Дефекты
   - Сообщить о дефекте (POST defect/, partner)
   - Просмотр дефектов (admin)
   - Подтвердить дефект (admin) → проверить уменьшение долга
   - Отклонить дефект (admin)

L. Возвраты
   - Создать возврат (POST return-items/)
   - Проверить уменьшение долга

M. Оплата долга
   - Частичная оплата (pay-debt, 500 сом)
   - Ещё одна частичная (1000 сом)
   - Полное закрытие долга
   - Попытка переплаты → ошибка

N. Расходы партнёра
   - Создать запись расхода (partner)
   - Список расходов за период

O. Статистика (Reports)
   - Статистика admin: GET /api/reports/statistics/
   - Статистика партнёра: GET /api/reports/partners/statistics/
   - История магазина: GET /api/reports/store-history/1/
   - Профиль партнёра: GET /api/reports/partners/profile/
   - Трекер заказов: GET /api/reports/partners/tracker/

P. Уведомления
   - Регистрация FCM-токена
   - Просмотр списка уведомлений
   - Пометить как прочитанное

Q. Граничные случаи
   - Все негативные сценарии из раздела 16

R. Очистка
   - Проверка clean_database() не ломает другие тесты
```

### 17.5 Критические пути (smoke tests, минимум)

```
1. store логинится → создаёт заказ
2. admin утверждает → partner подтверждает
3. partner создаёт дефект → admin подтверждает → долг уменьшается
4. store/partner платит → долг закрывается
5. ProductionBatch создаётся → cost_price обновляется
```

---

## ПРИЛОЖЕНИЕ: СВОДНАЯ ТАБЛИЦА РОЛЕЙ И РАЗРЕШЕНИЙ

| Действие                       | Admin | Partner | Store |
|--------------------------------|-------|---------|-------|
| Просмотр всех заказов          | ✅    | ✅      | ❌    |
| Создание preorder              | ❌    | ❌      | ✅    |
| Утверждение заказа             | ✅    | ❌      | ❌    |
| Создание manual order          | ❌    | ✅      | ❌    |
| Подтверждение доставки         | ❌    | ✅      | ❌    |
| Просмотр своих заказов         | ❌    | ❌      | ✅    |
| Создание Expense               | ✅    | ❌      | ❌    |
| Создание Product               | ✅    | ❌      | ❌    |
| Создание ProductRecipe         | ✅    | ❌      | ❌    |
| Создание ProductionBatch       | ✅    | ❌      | ❌    |
| Сообщить о дефекте             | ❌    | ✅      | ❌    |
| Подтвердить дефект             | ✅    | ❌      | ❌    |
| Создать возврат                | ❌    | ✅      | ❌    |
| Принять оплату долга           | ❌    | ✅      | ❌    |
| Просмотр магазина              | ✅    | ✅      | ✅    |
| Заморозка магазина             | ✅    | ❌      | ❌    |
| Статистика (глобальная)        | ✅    | ❌      | ❌    |
| Статистика партнёра            | ❌    | ✅      | ❌    |
| История магазина               | ✅    | ✅      | ❌    |
| FCM токен (свой)               | ✅    | ✅      | ✅    |

---

*Документ сгенерирован на основе анализа кода БайЭл v3.0+*
