"""
HTTP load test for the ambulance routing API.

Sends concurrent route requests and measures latency, throughput, and success rate.

Requirements:
    pip install httpx

Usage (server must be running first):
    PYTHONPATH=. uvicorn api.main:app --reload &
    python benchmarks/load_test.py --url http://localhost:8000 --concurrency 100 500 1000

Output:
    Prints a markdown-formatted summary table.
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)


ROUTE_PAYLOAD = {
    "ambulance_id": None,
    "current_location": {"lat": 12.97, "lon": 77.59},
    "destination": {"lat": 12.965, "lon": 77.60},
    "departure_time": "2026-06-12T08:00:00Z",
}


async def _send_one(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
) -> Tuple[int, float]:
    """Return (status_code, latency_ms)."""
    start = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, timeout=10.0)
        status = resp.status_code
    except Exception:
        status = 0
    latency = (time.perf_counter() - start) * 1000
    return status, latency


async def run_load_test(
    base_url: str,
    n_requests: int,
    concurrency: int,
) -> dict:
    """Run n_requests against /route_ambulance with the given concurrency level."""
    endpoint = f"{base_url}/route_ambulance"
    semaphore = asyncio.Semaphore(concurrency)
    results: List[Tuple[int, float]] = []

    async def bounded(i: int):
        payload = {**ROUTE_PAYLOAD, "ambulance_id": f"LOAD-{i:06d}"}
        async with semaphore:
            r = await _send_one(client, endpoint, payload)
        results.append(r)

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=concurrency + 50)) as client:
        wall_start = time.perf_counter()
        await asyncio.gather(*[bounded(i) for i in range(n_requests)])
        wall_elapsed = time.perf_counter() - wall_start

    statuses = [s for s, _ in results]
    latencies = [l for _, l in results]
    successes = sum(1 for s in statuses if s == 200)

    return {
        "n_requests": n_requests,
        "concurrency": concurrency,
        "wall_elapsed_s": wall_elapsed,
        "throughput_rps": n_requests / wall_elapsed if wall_elapsed > 0 else 0,
        "success_rate_pct": 100.0 * successes / n_requests if n_requests else 0,
        "latency_min_ms": min(latencies),
        "latency_max_ms": max(latencies),
        "latency_mean_ms": statistics.mean(latencies),
        "latency_p50_ms": statistics.median(latencies),
        "latency_p95_ms": _percentile(latencies, 95),
        "latency_p99_ms": _percentile(latencies, 99),
        "successes": successes,
        "failures": n_requests - successes,
    }


def _percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def print_report(results: List[dict]) -> None:
    print()
    print("## Load Test Results")
    print()
    print(
        f"{'Requests':>10} {'Concurrency':>12} {'Throughput':>12} {'Success %':>10} "
        f"{'P50 ms':>8} {'P95 ms':>8} {'P99 ms':>8} {'Max ms':>8}"
    )
    print("-" * 90)
    for r in results:
        print(
            f"{r['n_requests']:>10} {r['concurrency']:>12} "
            f"{r['throughput_rps']:>11.1f}/s {r['success_rate_pct']:>9.1f}% "
            f"{r['latency_p50_ms']:>8.1f} {r['latency_p95_ms']:>8.1f} "
            f"{r['latency_p99_ms']:>8.1f} {r['latency_max_ms']:>8.1f}"
        )
    print()


async def _main(base_url: str, concurrency_levels: List[int], n_requests: int) -> None:
    all_results = []
    for concurrency in concurrency_levels:
        print(f"Running {n_requests} requests @ concurrency={concurrency} …", flush=True)
        result = await run_load_test(base_url, n_requests, concurrency)
        all_results.append(result)
        print(
            f"  -> {result['throughput_rps']:.1f} req/s  "
            f"success={result['success_rate_pct']:.1f}%  "
            f"P50={result['latency_p50_ms']:.1f}ms"
        )

    print_report(all_results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ambulance routing API load test")
    parser.add_argument("--url", default="http://localhost:8000", help="Base API URL")
    parser.add_argument(
        "--concurrency",
        nargs="+",
        type=int,
        default=[100, 500, 1000],
        help="Concurrency levels to test (space-separated)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=1000,
        help="Total number of requests per concurrency level",
    )
    args = parser.parse_args()

    asyncio.run(_main(args.url, args.concurrency, args.requests))
