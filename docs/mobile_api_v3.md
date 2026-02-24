# API v3.0 — Изменения для мобильного разработчика

> **Дата**: 18.02.2026  
> **Версия**: 3.0  
> **Базовый URL**: `https://your-domain.com/api/`  
> **Авторизация**: `Authorization: Bearer <access_token>`

---

## Содержание

1. [Обзор изменений](#обзор-изменений)
2. [Экран «Учёт данных» — Сохранение](#1-экран-учёт-данных--сохранение-save-accounting)
3. [Механический учёт — Получение](#2-механический-учёт--получение-mechanical-accounting)
4. [Рецепты товаров — Создание](#3-рецепты-товаров--создание-product-recipes)
5. [Таблица учёта — Получение](#4-таблица-учёта--получение-accounting-table)

---

## Обзор изменений

| Что изменилось | Endpoint | Метод | Суть |
|---|---|---|---|
| **Единый POST сохранения** | `products/save-accounting/` | POST | Добавлена секция `recipe_items` (котлованская часть) |
| **Обогащённый ответ** | `expenses/mechanical-accounting/` | GET | Добавлены `expense_type`, `expense_state`, `apply_type`, `monthly_amount` |
| **Новые поля рецепта** | `product-recipes/` | POST | Поддержка `absolute_quantity` и `product_quantity` |
| **Поддержка per_volume** | `expenses/` | POST/GET | Новый `unit_type: "per_volume"` (По объёму, литр) |

---

## 1. Экран «Учёт данных» — Сохранение (save-accounting)

### `POST /api/products/products/save-accounting/`

Единая кнопка «Сохранить» отправляет **один** запрос с тремя секциями.  
Все секции **опциональны** — можно отправить только то что заполнено.

### Request Body

```json
{
  "mechanical_expenses": [
    {
      "expense_id": 5,
      "amount": "800.00"
    }
  ],
  "recipe_items": [
    {
      "product_id": 1,
      "expense_id": 2,
      "absolute_quantity": "80",
      "product_quantity": "40"
    },
    {
      "product_id": 1,
      "expense_id": 3,
      "absolute_quantity": "40"
    }
  ],
  "production_batches": [
    {
      "product_id": 1,
      "input_type": "quantity",
      "quantity": "200",
      "date": "2026-02-18",
      "notes": "Утренняя партия"
    }
  ]
}
```

### Описание секций

#### `mechanical_expenses` — Механические расходы

| Поле | Тип | Обаз. | Описание |
|------|-----|-------|----------|
| `expense_id` | int | ✅ | ID расхода |
| `amount` | decimal | ✅ | Сумма расхода за день (≥ 0) |

#### `recipe_items` — Котлованская часть (рецепты) ⭐ НОВОЕ

Создаёт или **обновляет** рецепт товара (связь товар ↔ расход).  
Если рецепт уже существует — обновляется, дубликаты не создаются.

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| `product_id` | int | ✅ | ID товара |
| `expense_id` | int | ✅ | ID расхода |
| `absolute_quantity` | decimal | ❌ | Абсолютное количество расхода (например, 80 кг фарша) |
| `product_quantity` | decimal | ❌ | Количество товара (нужно для Сюзерена, например, 40 шт = 80/40 = 2 кг/шт) |
| `quantity_per_unit` | decimal | ❌ | Прямой ввод: расход на ед. товара (для Сюзерена) |
| `proportion` | decimal | ❌ | Прямой ввод: пропорция от Сюзерена (для Обывателя) |

**Два режима ввода:**

1. **Абсолютный** (рекомендуемый): передать `absolute_quantity` + `product_quantity` (для Сюзерена)
   - Сервер автоматически посчитает `quantity_per_unit` и `proportion`
2. **Прямой**: передать `quantity_per_unit` или `proportion` напрямую

#### `production_batches` — Производственные партии (без изменений)

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| `product_id` | int | ✅ | ID товара |
| `input_type` | string | ✅ | `"quantity"` или `"suzerain"` |
| `quantity` | decimal | ❌ | Количество товара (при `input_type=quantity`) |
| `suzerain_quantity` | decimal | ❌ | Количество сюзерена (при `input_type=suzerain`) |
| `date` | date | ❌ | Дата партии (по умолчанию — сегодня) |
| `notes` | string | ❌ | Заметки |

### Response `200 OK`

```json
{
  "mechanical_updated": 1,
  "recipes_saved": 2,
  "batches_created": 0
}
```

| Поле | Описание |
|------|----------|
| `mechanical_updated` | Сколько механических расходов обновлено |
| `recipes_saved` | Сколько рецептов создано/обновлено |
| `batches_created` | Сколько партий создано |

### Примеры

<details>
<summary>Только механика (старый формат, совместим)</summary>

```json
// Request
{
  "mechanical_expenses": [
    {"expense_id": 5, "amount": "900"}
  ]
}

// Response 200
{
  "mechanical_updated": 1,
  "recipes_saved": 0,
  "batches_created": 0
}
```
</details>

<details>
<summary>Только котлован (рецепты)</summary>

```json
// Request
{
  "recipe_items": [
    {
      "product_id": 1,
      "expense_id": 2,
      "absolute_quantity": "80",
      "product_quantity": "40"
    }
  ]
}

// Response 200
{
  "mechanical_updated": 0,
  "recipes_saved": 1,
  "batches_created": 0
}
```
</details>

<details>
<summary>Всё вместе</summary>

```json
// Request
{
  "mechanical_expenses": [
    {"expense_id": 5, "amount": "800"}
  ],
  "recipe_items": [
    {"product_id": 1, "expense_id": 2, "absolute_quantity": "80", "product_quantity": "40"},
    {"product_id": 1, "expense_id": 3, "absolute_quantity": "40"}
  ],
  "production_batches": [
    {"product_id": 1, "input_type": "quantity", "quantity": "200"}
  ]
}

// Response 200
{
  "mechanical_updated": 1,
  "recipes_saved": 2,
  "batches_created": 1
}
```
</details>

---

## 2. Механический учёт — Получение (mechanical-accounting)

### `GET /api/products/expenses/mechanical-accounting/`

Возвращает **только накладные** (`expense_type = "overhead"`) расходы с `expense_state = "mechanical"`.
Физические расходы (ингредиенты) **не** отображаются — они управляются через рецепты товаров (ProductRecipe).

### Response `200 OK`

```json
{
  "mechanical_expenses": [
    {
      "id": 5,
      "name": "Солярка",
      "expense_type": "overhead",
      "expense_status": "vassal",
      "expense_state": "mechanical",
      "apply_type": "universal",
      "monthly_amount": "0.00",
      "daily_amount": "700.00"
    },
    {
      "id": 6,
      "name": "Обед",
      "expense_type": "overhead",
      "expense_status": "vassal",
      "expense_state": "mechanical",
      "apply_type": "universal",
      "monthly_amount": "0.00",
      "daily_amount": "600.00"
    }
  ]
}
```

### ⭐ Новые поля (добавлены в v3.0)

| Поле | Тип | Описание | Возможные значения |
|------|-----|----------|-------------------|
| `expense_type` | string | Тип расхода (всегда `"overhead"` тут) | `"overhead"` |
| `expense_state` | string | Состояние (всегда mechanical тут) | `"mechanical"` |
| `apply_type` | string | Тип применения | `"regular"`, `"universal"` |
| `monthly_amount` | decimal | Месячная сумма | `"0.00"` |

### Поля которые были ранее

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | int | ID расхода |
| `name` | string | Название |
| `expense_status` | string | `"suzerain"`, `"vassal"`, `"civilian"` |
| `daily_amount` | decimal | Дневная сумма (редактируется пользователем) |

---

## 3. Рецепты товаров — Создание (product-recipes)

### `POST /api/products/product-recipes/`

### ⭐ Новые поля (добавлены в v3.0)

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| `absolute_quantity` | decimal | ❌ | Абсолютное количество расхода |
| `product_quantity` | decimal | ❌ | Количество товара (для расчёта `quantity_per_unit`) |

### Request Body — вариант с `absolute_quantity`

```json
{
  "product": 1,
  "expense": 2,
  "absolute_quantity": "80.0000",
  "product_quantity": "40.00"
}
```

### Request Body — старый формат (совместимость)

```json
{
  "product": 1,
  "expense": 2,
  "quantity_per_unit": "2.0000"
}
```

### Response `201 Created`

```json
{
  "product": 1,
  "expense": 2,
  "quantity_per_unit": "2.0000",
  "proportion": null,
  "absolute_quantity": "80.0000",
  "product_quantity": "40.00"
}
```

### Логика автоматического расчёта

| Тип расхода | Ввод | Авторасчёт |
|-------------|------|------------|
| **Сюзерен** | `absolute_quantity` + `product_quantity` | `quantity_per_unit = absolute / product_quantity` |
| **Обыватель** | `absolute_quantity` | `proportion = absolute / суз.absolute_quantity` |

> ⚠️ Для **Сюзерена** с `absolute_quantity` — поле `product_quantity` **обязательно**

---

## 4. Таблица учёта — Получение (accounting-table)

### `GET /api/products/products/accounting-table/`

⭐ Новые поля: `total_physical_cost`, `total_overhead_cost`, `profit_per_unit`.

### Response `200 OK`

```json
{
  "period_days": 11,
  "date_from": "2026-02-13",
  "date_to": "2026-02-24",
  "products": [
    {
      "id": 2,
      "name": "Котлеты куриные",
      "markup_percentage": 35.0,
      "final_price": 42.75,
      "cost_per_unit": 31.67,
      "total_expense": 6334.0,
      "total_physical_cost": 3200.0,
      "total_overhead_cost": 3134.0,
      "revenue": 8550.0,
      "profit": 2216.0,
      "profit_per_unit": 11.08,
      "physical_expenses": [
        {
          "id": 1,
          "name": "Фарш говяжий",
          "is_suzerain": true,
          "quantity": 400.0,
          "unit_price": 810.0,
          "unit": "per_weight",
          "unit_label": "кг.",
          "total": 3200.0
        }
      ],
      "overhead_expenses": [
        {
          "id": 4,
          "name": "Аренда помещения",
          "apply_type": "universal",
          "total": 2200.0
        },
        {
          "id": 5,
          "name": "Солярка",
          "apply_type": "universal",
          "total": 934.0
        }
      ]
    }
  ],
  "totals": {
    "total_expense": 6334.0,
    "total_revenue": 8550.0,
    "net_profit": 2216.0
  }
}
```

### Значения `unit` в `physical_expenses`

| Значение | Описание |
|----------|----------|
| `"per_weight"` | По весу (кг) |
| `"per_piece"` | По штукам |
| `"per_volume"` | По объёму (литр) ⭐ |

---

## Справочник значений (enums)

### `expense_type`
| Значение | Описание |
|----------|----------|
| `physical` | Физический расход (входит в себестоимость) |
| `overhead` | Накладной расход (распределяется по объёму) |

### `expense_status`
| Значение | Описание |
|----------|----------|
| `suzerain` | Сюзерен (главный ингредиент) |
| `vassal` | Вассал (зависит от Сюзерена) |
| `civilian` | Обыватель (обычный) |

### `expense_state`
| Значение | Описание |
|----------|----------|
| `automatic` | Автоматический (рассчитывается из рецепта) |
| `mechanical` | Механический (вводится вручную ежедневно) |

### `apply_type`
| Значение | Описание |
|----------|----------|
| `regular` | Обычный (привязан к конкретным товарам) |
| `universal` | Универсальный (применяется ко всем товарам) |

### `unit_type`
| Значение | Описание |
|----------|----------|
| `per_weight` | По весу (кг) |
| `per_piece` | По штукам |
| `per_volume` | По объёму (литр) ⭐ Новый |

---

## Обратная совместимость

> ✅ Все изменения **обратно совместимы**. Старые запросы без новых полей продолжают работать.

| Сценарий | Поведение |
|----------|-----------|
| `save-accounting` без `recipe_items` | Работает как раньше |
| `product-recipes` без `absolute_quantity` | Работает как раньше (прямой ввод `quantity_per_unit`/`proportion`) |
| `mechanical-accounting` — новые поля | Добавлены в ответ, не ломают парсинг |
