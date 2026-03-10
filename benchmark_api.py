"""
Полный бенчмарк ВСЕХ API эндпоинтов.

Использование:
  python benchmark_api.py --label "BEFORE"
  python benchmark_api.py --label "AFTER"

Результаты сохраняются в benchmark_results.txt
"""

import requests
import time
import statistics
import argparse
from datetime import datetime


# ============================================================================
# НАСТРОЙКИ
# ============================================================================
BASE_URL = "https://baielapp.com.kg/api"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzgwOTE0NDg2LCJpYXQiOjE3NzMxMzg0ODYsImp0aSI6ImNmMWNjMjlhY2NmZjQ2ZDNhYTNiNzYyYzMwNDYxODBlIiwidXNlcl9pZCI6IjQifQ.scvb3CgMDxMMEVcqTWCwX9a8DQpnE_Ht3Gf2mWrqMMQ"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

REPEAT = 3  # Повторов на каждый эндпоинт

# ============================================================================
# ВСЕ GET-ЭНДПОИНТЫ (безопасные для бенчмарка, не меняют данные)
# ============================================================================
ENDPOINTS = [
    # --- AUTH ---
    ("GET", "/auth/profile/",                        "Auth: Профиль"),

    # --- PRODUCTS ---
    ("GET", "/products/products/",                    "Products: Список товаров"),
    ("GET", "/products/products/1/",                  "Products: Детали товара"),
    ("GET", "/products/expenses/",                    "Products: Расходы"),
    ("GET", "/products/expenses/mechanical-accounting/", "Products: Мех. учёт"),
    ("GET", "/products/product-recipes/",             "Products: Рецепты"),
    ("GET", "/products/production-batches/",          "Products: Партии"),
    ("GET", "/products/product-images/",              "Products: Изображения"),
    ("GET", "/products/partner-expenses/",            "Products: Расходы партнёра"),
    ("GET", "/products/products/accounting-table/",   "Products: Таблица учёта"),

    # --- STORES ---
    ("GET", "/stores/regions/",                       "Stores: Регионы"),
    ("GET", "/stores/cities/",                        "Stores: Города"),
    ("GET", "/stores/stores/",                        "Stores: Список магазинов"),
    ("GET", "/stores/stores/?order_type=preorder",    "Stores: Магазины (предзаказ)"),
    ("GET", "/stores/stores/?order_type=manual",      "Stores: Магазины (ручной)"),
    ("GET", "/stores/stores/4/",                      "Stores: Детали магазина"),
    ("GET", "/stores/stores/4/basket/",               "Stores: Корзина"),
    ("GET", "/stores/stores/4/inventory/",            "Stores: Инвентарь магазина"),
    ("GET", "/stores/partner-inventory/",             "Stores: Инвентарь партнёра"),
    ("GET", "/stores/store-inventory/",               "Stores: Store Inventory"),

    # --- ORDERS ---
    ("GET", "/orders/store-orders/",                  "Orders: Список заказов"),
    ("GET", "/orders/store-orders/my-orders/",        "Orders: Мои заказы"),
    ("GET", "/orders/store-orders/pending-preorders/", "Orders: Ожидающие предзаказы"),
    ("GET", "/orders/partner-requests/",              "Orders: Заявки партнёров"),
    ("GET", "/orders/returned-items/",                "Orders: Возвраты"),

    # --- REPORTS ---
    ("GET", "/reports/statistics/",                   "Reports: Статистика"),
    ("GET", "/reports/partners/statistics/",          "Reports: Статистика партнёров"),
    ("GET", "/reports/partners/profile/",             "Reports: Профиль партнёра"),
    ("GET", "/reports/partners/tracker/",             "Reports: Трекер партнёра"),

    # --- CHATS ---
    ("GET", "/chats/",                                "Chats: Список чатов"),
    ("GET", "/chats/users/",                          "Chats: Доступные пользователи"),

    # --- HEALTH ---
    ("GET", "/../health/",                            "Health: Health Check"),
]


def benchmark_endpoint(method, path, name):
    """Замеряет время ответа."""
    # Специальный случай для health
    if path.startswith("/../"):
        url = BASE_URL.replace("/api", "") + path.replace("/../", "/")
    else:
        url = BASE_URL + path

    times = []
    status_code = None

    for i in range(REPEAT):
        start = time.perf_counter()
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            status_code = resp.status_code
        except requests.exceptions.Timeout:
            times.append(30.0)
            status_code = "TIMEOUT"
        except Exception as e:
            times.append(-1)
            status_code = f"ERR"

    valid = [t for t in times if t > 0]
    avg = statistics.mean(valid) * 1000 if valid else -1
    mn = min(valid) * 1000 if valid else -1
    mx = max(valid) * 1000 if valid else -1

    return {
        "name": name,
        "status": status_code,
        "min": mn,
        "avg": avg,
        "max": mx,
        "times": valid,
    }


def run_benchmark(label):
    """Полный бенчмарк."""
    print(f"\n{'='*70}")
    print(f"  ПОЛНЫЙ БЕНЧМАРК: {label}")
    print(f"  Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Сервер: {BASE_URL}")
    print(f"  Повторов: {REPEAT}")
    print(f"  Эндпоинтов: {len(ENDPOINTS)}")
    print(f"{'='*70}\n")

    results = []
    slow_endpoints = []

    for i, (method, path, name) in enumerate(ENDPOINTS, 1):
        r = benchmark_endpoint(method, path, name)
        results.append(r)

        status_icon = "✅" if str(r["status"]).startswith("2") else "⚠️ " if str(r["status"]).startswith("4") else "❌"
        bar = "█" * int(r["avg"] / 10) if r["avg"] > 0 else ""
        print(f"  [{i:2d}/{len(ENDPOINTS)}] {status_icon} {r['avg']:>6.0f}ms  {name:<35} HTTP {r['status']}  {bar}")

        if r["avg"] > 200:
            slow_endpoints.append(r)

    # =====================================================================
    # СВОДКА
    # =====================================================================
    all_avgs = [r["avg"] for r in results if r["avg"] > 0]

    print(f"\n{'='*70}")
    print(f"  СВОДКА: {label}")
    print(f"{'='*70}")

    if all_avgs:
        print(f"  Общее среднее:      {statistics.mean(all_avgs):.0f}ms")
        print(f"  Медиана:            {statistics.median(all_avgs):.0f}ms")
        print(f"  Самый быстрый:      {min(all_avgs):.0f}ms")
        print(f"  Самый медленный:    {max(all_avgs):.0f}ms")

    if slow_endpoints:
        print(f"\n  🐌 МЕДЛЕННЫЕ ЭНДПОИНТЫ (>200мс):")
        for r in sorted(slow_endpoints, key=lambda x: -x["avg"]):
            print(f"     {r['avg']:>6.0f}ms  {r['name']}")

    # Группируем по модулям
    modules = {}
    for r in results:
        module = r["name"].split(":")[0].strip()
        if module not in modules:
            modules[module] = []
        modules[module].append(r["avg"])

    print(f"\n  📊 СРЕДНЕЕ ПО МОДУЛЯМ:")
    for module, avgs in sorted(modules.items(), key=lambda x: -statistics.mean(x[1])):
        valid_avgs = [a for a in avgs if a > 0]
        if valid_avgs:
            print(f"     {statistics.mean(valid_avgs):>6.0f}ms  {module} ({len(valid_avgs)} endpoints)")

    print(f"{'='*70}\n")

    # =====================================================================
    # СОХРАНЯЕМ В ФАЙЛ
    # =====================================================================
    with open("benchmark_results.txt", "a") as f:
        f.write(f"\n{'='*70}\n")
        f.write(f"ПОЛНЫЙ БЕНЧМАРК: {label}\n")
        f.write(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Эндпоинтов: {len(ENDPOINTS)}, Повторов: {REPEAT}\n\n")

        f.write(f"{'Эндпоинт':<40} {'Status':>6} {'Min':>8} {'Avg':>8} {'Max':>8}\n")
        f.write(f"{'-'*40} {'-'*6} {'-'*8} {'-'*8} {'-'*8}\n")

        for r in results:
            f.write(f"{r['name']:<40} {str(r['status']):>6} {r['min']:>7.0f}ms {r['avg']:>7.0f}ms {r['max']:>7.0f}ms\n")

        if all_avgs:
            f.write(f"\nОбщее среднее: {statistics.mean(all_avgs):.0f}ms\n")
            f.write(f"Медиана: {statistics.median(all_avgs):.0f}ms\n")
            f.write(f"Min: {min(all_avgs):.0f}ms, Max: {max(all_avgs):.0f}ms\n")

        if slow_endpoints:
            f.write(f"\nМедленные (>200мс):\n")
            for r in sorted(slow_endpoints, key=lambda x: -x["avg"]):
                f.write(f"  {r['avg']:>6.0f}ms  {r['name']}\n")

        f.write(f"{'='*70}\n")

    print("✅ Результаты добавлены в benchmark_results.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Полный API Benchmark")
    parser.add_argument("--label", default="TEST", help="Метка (BEFORE / AFTER)")
    args = parser.parse_args()
    run_benchmark(args.label)
