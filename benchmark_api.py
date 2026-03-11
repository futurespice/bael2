"""
Полный бенчмарк ВСЕХ API эндпоинтов + тесты кеша.

Использование:
  python benchmark_api.py --label "BEFORE"
  python benchmark_api.py --label "AFTER"
  python benchmark_api.py --label "CACHE" --mode cache

Режимы (--mode):
  all   — полный бенчмарк + тесты кеша (по умолчанию)
  quick — только основные эндпоинты
  cache — только тесты кеша и повторных запросов

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
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzczMjAwNDk5LCJpYXQiOjE3NzMxOTY4OTksImp0aSI6IjgxNzkwNDIzMDFlMDQ3MGVhZTZiYzYyNTRlNDgyYmFkIiwidXNlcl9pZCI6IjQifQ.uijhrEbtN6jsLkcnLraGTmpjRwBP_yOiTYtH0YB-V5M"

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

# Эндпоинты для тестов кеша (самые тяжёлые)
CACHE_TEST_ENDPOINTS = [
    ("GET", "/products/products/",                    "Products: Список товаров"),
    ("GET", "/stores/stores/",                        "Stores: Список магазинов"),
    ("GET", "/orders/store-orders/",                  "Orders: Список заказов"),
    ("GET", "/chats/",                                "Chats: Список чатов"),
    ("GET", "/reports/statistics/",                   "Reports: Статистика"),
    ("GET", "/products/products/accounting-table/",   "Products: Таблица учёта"),
    ("GET", "/../health/",                            "Health: Health Check"),
]


def _build_url(path):
    if path.startswith("/../"):
        return BASE_URL.replace("/api", "") + path.replace("/../", "/")
    return BASE_URL + path


def _request(url):
    """Один запрос, возвращает (время_мс, статус_код)."""
    start = time.perf_counter()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, resp.status_code
    except requests.exceptions.Timeout:
        return 30000, "TIMEOUT"
    except Exception:
        return -1, "ERR"


def benchmark_endpoint(method, path, name):
    """Замеряет время ответа."""
    url = _build_url(path)
    times = []
    status_code = None

    for i in range(REPEAT):
        elapsed, sc = _request(url)
        times.append(elapsed)
        status_code = sc

    valid = [t for t in times if t > 0]
    avg = statistics.mean(valid) if valid else -1

    return {
        "name": name,
        "status": status_code,
        "min": min(valid) if valid else -1,
        "avg": avg,
        "max": max(valid) if valid else -1,
        "times": valid,
    }


def run_benchmark(label):
    """Полный бенчмарк всех эндпоинтов."""
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

    # Сводка
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

    return results


def run_cache_tests(label):
    """
    Тесты кеша и повторных запросов.

    1. Cold vs Warm — первый запрос vs последующие
    2. Стресс-тест — 10 запросов подряд
    3. Пагинация — страница 1 vs 2
    4. Размер ответов
    """
    print(f"\n{'='*70}")
    print(f"  🧊 ТЕСТ КЕША И СТАБИЛЬНОСТИ: {label}")
    print(f"  Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")

    all_results = []

    # === ТЕСТ 1: Cold vs Warm ===
    print("  --- Cold vs Warm (1-й запрос vs среднее 2-5) ---\n")
    print(f"  {'Эндпоинт':<35} {'Cold':>6} {'Warm':>6} {'Разница':>8} {'Вывод'}")
    print(f"  {'-'*35} {'-'*6} {'-'*6} {'-'*8} {'-'*15}")

    for method, path, name in CACHE_TEST_ENDPOINTS:
        url = _build_url(path)
        times = []
        for _ in range(5):
            elapsed, _ = _request(url)
            times.append(elapsed)

        cold = times[0]
        warm = statistics.mean(times[1:]) if len(times) > 1 else cold
        diff = cold - warm
        pct = (diff / warm * 100) if warm > 0 else 0

        if diff > 50:
            verdict = "🥶 Медленный cold"
        elif diff > 20:
            verdict = "⚠️  Cold > Warm"
        else:
            verdict = "✅ Стабильно"

        print(f"  {name:<35} {cold:>5.0f}ms {warm:>5.0f}ms {diff:>+7.0f}ms {verdict}")
        all_results.append({
            "test": "cold_vs_warm",
            "name": name,
            "cold": cold,
            "warm": warm,
            "diff": diff,
        })

    # === ТЕСТ 2: Стресс-тест (10 запросов подряд) ===
    print(f"\n  --- Стресс-тест (10 быстрых запросов подряд) ---\n")
    print(f"  {'Эндпоинт':<35} {'Min':>5} {'Avg':>5} {'Max':>5} {'StdDev':>7} {'Вывод'}")
    print(f"  {'-'*35} {'-'*5} {'-'*5} {'-'*5} {'-'*7} {'-'*15}")

    stress_endpoints = [
        ("GET", "/products/products/",   "Products: Список товаров"),
        ("GET", "/stores/stores/",       "Stores: Список магазинов"),
        ("GET", "/orders/store-orders/", "Orders: Список заказов"),
        ("GET", "/chats/",               "Chats: Список чатов"),
        ("GET", "/auth/profile/",        "Auth: Профиль"),
        ("GET", "/../health/",           "Health: Health Check"),
    ]

    for method, path, name in stress_endpoints:
        url = _build_url(path)
        times = []
        for _ in range(10):
            elapsed, _ = _request(url)
            if elapsed > 0:
                times.append(elapsed)

        if times:
            mn = min(times)
            avg = statistics.mean(times)
            mx = max(times)
            std = statistics.stdev(times) if len(times) > 1 else 0

            if std > 50:
                verdict = "⚠️  Нестабильно"
            elif mx > avg * 2:
                verdict = "⚠️  Всплески"
            else:
                verdict = "✅ Стабильно"

            print(f"  {name:<35} {mn:>4.0f}ms {avg:>4.0f}ms {mx:>4.0f}ms {std:>6.1f}ms {verdict}")
            all_results.append({
                "test": "stress",
                "name": name,
                "min": mn,
                "avg": avg,
                "max": mx,
                "std": std,
                "count": len(times),
            })

    # === ТЕСТ 3: Пагинация (1-я страница vs 2-я) ===
    print(f"\n  --- Пагинация (страница 1 vs страница 2) ---\n")
    print(f"  {'Эндпоинт':<35} {'Стр.1':>6} {'Стр.2':>6} {'Разница':>8}")
    print(f"  {'-'*35} {'-'*6} {'-'*6} {'-'*8}")

    pagination_endpoints = [
        ("/products/products/",   "Products"),
        ("/stores/stores/",       "Stores"),
        ("/orders/store-orders/", "Orders"),
    ]

    for path, name in pagination_endpoints:
        url1 = _build_url(path)
        url2 = _build_url(f"{path}?page=2")

        # Среднее из 3 запросов для точности
        t1_list = [_request(url1)[0] for _ in range(3)]
        t2_list = [_request(url2)[0] for _ in range(3)]
        t1 = statistics.mean([t for t in t1_list if t > 0]) if any(t > 0 for t in t1_list) else -1
        t2 = statistics.mean([t for t in t2_list if t > 0]) if any(t > 0 for t in t2_list) else -1

        if t1 > 0 and t2 > 0:
            diff = t2 - t1
            print(f"  {name + ': page 1 vs 2':<35} {t1:>5.0f}ms {t2:>5.0f}ms {diff:>+7.0f}ms")

    # === ТЕСТ 4: Размер ответа ===
    print(f"\n  --- Размер ответов ---\n")
    print(f"  {'Эндпоинт':<35} {'Размер':>10} {'Время':>6}")
    print(f"  {'-'*35} {'-'*10} {'-'*6}")

    for method, path, name in CACHE_TEST_ENDPOINTS:
        url = _build_url(path)
        start = time.perf_counter()
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            elapsed = (time.perf_counter() - start) * 1000
            size = len(resp.content)
            if size > 1024 * 1024:
                size_str = f"{size / 1024 / 1024:.1f} MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            print(f"  {name:<35} {size_str:>10} {elapsed:>5.0f}ms")
        except Exception:
            print(f"  {name:<35} {'ERR':>10}")

    print(f"\n{'='*70}\n")
    return all_results


def save_results(label, endpoint_results, cache_results):
    """Сохранить все результаты в файл."""
    with open("benchmark_results.txt", "a") as f:
        f.write(f"\n{'='*70}\n")
        f.write(f"БЕНЧМАРК: {label}\n")
        f.write(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        if endpoint_results:
            f.write(f"{'Эндпоинт':<40} {'Status':>6} {'Min':>8} {'Avg':>8} {'Max':>8}\n")
            f.write(f"{'-'*40} {'-'*6} {'-'*8} {'-'*8} {'-'*8}\n")

            for r in endpoint_results:
                f.write(f"{r['name']:<40} {str(r['status']):>6} {r['min']:>7.0f}ms {r['avg']:>7.0f}ms {r['max']:>7.0f}ms\n")

            all_avgs = [r["avg"] for r in endpoint_results if r["avg"] > 0]
            if all_avgs:
                f.write(f"\nОбщее среднее: {statistics.mean(all_avgs):.0f}ms\n")
                f.write(f"Медиана: {statistics.median(all_avgs):.0f}ms\n")
                f.write(f"Min: {min(all_avgs):.0f}ms, Max: {max(all_avgs):.0f}ms\n")

        if cache_results:
            f.write(f"\n--- Тесты кеша ---\n")
            for r in cache_results:
                if r["test"] == "cold_vs_warm":
                    f.write(f"  {r['name']:<35} cold={r['cold']:.0f}ms warm={r['warm']:.0f}ms diff={r['diff']:+.0f}ms\n")
                elif r["test"] == "stress":
                    f.write(f"  {r['name']:<35} min={r['min']:.0f}ms avg={r['avg']:.0f}ms max={r['max']:.0f}ms std={r['std']:.1f}ms\n")

        f.write(f"{'='*70}\n")

    print("✅ Результаты добавлены в benchmark_results.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Полный API Benchmark")
    parser.add_argument("--label", default="TEST", help="Метка (BEFORE / AFTER)")
    parser.add_argument("--mode", default="all", choices=["all", "quick", "cache"],
                        help="Режим: all (всё), quick (только эндпоинты), cache (только кеш)")
    args = parser.parse_args()

    endpoint_results = []
    cache_results = []

    if args.mode in ("all", "quick"):
        endpoint_results = run_benchmark(args.label)

    if args.mode in ("all", "cache"):
        cache_results = run_cache_tests(args.label)

    save_results(args.label, endpoint_results, cache_results)
