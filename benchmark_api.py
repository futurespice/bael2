"""
Бенчмарк API скорости.

Использование:
  1. ДО деплоя:   python benchmark_api.py --label "BEFORE"
  2. Задеплоить изменения
  3. ПОСЛЕ деплоя: python benchmark_api.py --label "AFTER"

Результаты сохраняются в benchmark_results.txt
"""

import requests
import time
import statistics
import argparse
from datetime import datetime


# ============================================================================
# НАСТРОЙКИ — ПОМЕНЯЙ ТОКЕН НА АКТУАЛЬНЫЙ
# ============================================================================
BASE_URL = "https://baielapp.com.kg/api"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzgwOTE0NDg2LCJpYXQiOjE3NzMxMzg0ODYsImp0aSI6ImNmMWNjMjlhY2NmZjQ2ZDNhYTNiNzYyYzMwNDYxODBlIiwidXNlcl9pZCI6IjQifQ.scvb3CgMDxMMEVcqTWCwX9a8DQpnE_Ht3Gf2mWrqMMQ"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# Эндпоинты для тестирования
ENDPOINTS = [
    ("GET",  "/products/products/",       "Список товаров"),
    ("GET",  "/stores/stores/",           "Список магазинов"),
    ("GET",  "/auth/me/",                 "Профиль (auth check)"),
]

REPEAT = 5  # Сколько раз повторить каждый запрос


def benchmark_endpoint(method, path, name):
    """Замеряет время ответа эндпоинта."""
    url = BASE_URL + path
    times = []

    for i in range(REPEAT):
        start = time.perf_counter()
        try:
            if method == "GET":
                resp = requests.get(url, headers=HEADERS, timeout=30)
            elif method == "POST":
                resp = requests.post(url, headers=HEADERS, json={}, timeout=30)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            status = resp.status_code
        except requests.exceptions.Timeout:
            times.append(30.0)
            status = "TIMEOUT"
        except Exception as e:
            times.append(-1)
            status = f"ERROR: {e}"

        print(f"  [{i+1}/{REPEAT}] {name}: {elapsed*1000:.0f}ms (HTTP {status})")

    return times


def run_benchmark(label):
    """Запускает полный бенчмарк."""
    print(f"\n{'='*60}")
    print(f"  BENCHMARK: {label}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Server: {BASE_URL}")
    print(f"  Repeats per endpoint: {REPEAT}")
    print(f"{'='*60}\n")

    # Холодный старт — первый запрос после простоя
    print("--- COLD START (первый запрос) ---")
    cold_url = BASE_URL + "/products/products/"
    start = time.perf_counter()
    try:
        resp = requests.get(cold_url, headers=HEADERS, timeout=30)
        cold_time = time.perf_counter() - start
        print(f"  Cold start: {cold_time*1000:.0f}ms (HTTP {resp.status_code})")
    except Exception as e:
        cold_time = -1
        print(f"  Cold start: ERROR - {e}")

    print()

    results = {}

    for method, path, name in ENDPOINTS:
        print(f"--- {name} ({method} {path}) ---")
        times = benchmark_endpoint(method, path, name)
        valid_times = [t for t in times if t > 0]

        if valid_times:
            results[name] = {
                "min": min(valid_times) * 1000,
                "max": max(valid_times) * 1000,
                "avg": statistics.mean(valid_times) * 1000,
                "median": statistics.median(valid_times) * 1000,
                "p95": sorted(valid_times)[int(len(valid_times) * 0.95)] * 1000 if len(valid_times) > 1 else valid_times[0] * 1000,
            }
        print()

    # Вывод результатов
    print(f"\n{'='*60}")
    print(f"  РЕЗУЛЬТАТЫ: {label}")
    print(f"{'='*60}")
    print(f"  {'Эндпоинт':<25} {'Min':>8} {'Avg':>8} {'Median':>8} {'Max':>8} {'P95':>8}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    for name, stats in results.items():
        print(f"  {name:<25} {stats['min']:>7.0f}ms {stats['avg']:>7.0f}ms {stats['median']:>7.0f}ms {stats['max']:>7.0f}ms {stats['p95']:>7.0f}ms")

    print(f"\n  Cold start: {cold_time*1000:.0f}ms")
    print(f"{'='*60}\n")

    # Сохраняем в файл
    with open("benchmark_results.txt", "a") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"BENCHMARK: {label}\n")
        f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Cold start: {cold_time*1000:.0f}ms\n\n")
        f.write(f"{'Эндпоинт':<25} {'Min':>8} {'Avg':>8} {'Median':>8} {'Max':>8}\n")
        f.write(f"{'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8}\n")
        for name, stats in results.items():
            f.write(f"{name:<25} {stats['min']:>7.0f}ms {stats['avg']:>7.0f}ms {stats['median']:>7.0f}ms {stats['max']:>7.0f}ms\n")
        f.write(f"{'='*60}\n")

    print("✅ Результаты добавлены в benchmark_results.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="API Benchmark")
    parser.add_argument("--label", default="TEST", help="Метка теста (BEFORE / AFTER)")
    args = parser.parse_args()
    run_benchmark(args.label)
