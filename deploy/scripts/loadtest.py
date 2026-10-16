#!/usr/bin/env python
"""Dependency-free load tester for the AA Shinaka platform (Phase 12).

Standard library only — no new runtime dependency. It drives read-only endpoints
by default, so it is safe against staging, and it refuses to run when live
payments appear to be enabled so a load test can never take a real payment.

Usage
-----
    BASE_URL=https://staging.example.com \
        uv run python deploy/scripts/loadtest.py \
        --duration 30 --concurrency 10 \
        --paths /,/shop/,/training/,/healthz/ \
        --json perf.json

Exit codes: 0 success, 1 error rate exceeded, 2 bad usage / unsafe target.

This script prints *measured* numbers only. It makes no claim about capacity on
hardware it has not been run against.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PATHS = ["/", "/shop/", "/training/", "/healthz/"]
DEFAULT_TIMEOUT = 10.0


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _fetch(base_url: str, path: str, timeout: float) -> tuple[int, float]:
    """Return (status_code, elapsed_seconds). Status 0 means a transport error."""
    url = urllib.parse.urljoin(base_url, path)
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "aashinaka-loadtest/1"}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            response.read()
        return response.status, time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        return exc.code, time.perf_counter() - started
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, time.perf_counter() - started


def _worker(
    base_url: str,
    paths: list[str],
    deadline: float,
    timeout: float,
    results: list[tuple[int, float]],
    lock: threading.Lock,
    stop: threading.Event,
) -> None:
    local: list[tuple[int, float]] = []
    while not stop.is_set() and time.monotonic() < deadline:
        for path in paths:
            if stop.is_set() or time.monotonic() >= deadline:
                break
            local.append(_fetch(base_url, path, timeout))
    with lock:
        results.extend(local)


def _guard_target(base_url: str) -> None:
    """Refuse obviously live-payment targets; warn if the host is not staging."""
    enabled = os.environ.get("PAYSTACK_ENABLED", "").strip().lower() in {"1", "true", "yes"}
    if enabled and os.environ.get("ALLOW_LIVE_LOADTEST", "").strip().lower() != "yes":
        print(
            "Refusing to run: PAYSTACK_ENABLED is true. "
            "Set ALLOW_LIVE_LOADTEST=yes to override (owner approval required).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    lowered = base_url.lower()
    if not any(marker in lowered for marker in ("localhost", "127.0.0.1", "staging", ".invalid")):
        print(
            f"Note: target '{base_url}' does not look like a staging host. "
            "Load-test production only with owner approval.",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dependency-free load tester.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", "http://127.0.0.1:8000"),
        help="Target base URL (default $BASE_URL or http://127.0.0.1:8000).",
    )
    parser.add_argument("--duration", type=float, default=15.0, help="Seconds to run.")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent workers.")
    parser.add_argument(
        "--paths", default=",".join(DEFAULT_PATHS), help="Comma-separated paths to GET."
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.01,
        help="Fail (exit 1) if the error rate exceeds this fraction.",
    )
    parser.add_argument("--json", dest="json_path", default="", help="Write results as JSON.")
    args = parser.parse_args(argv)

    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    if not paths:
        parser.error("--paths must contain at least one path")
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    if args.duration <= 0:
        parser.error("--duration must be > 0")

    base_url = args.base_url if args.base_url.endswith("/") else args.base_url + "/"
    _guard_target(base_url)

    print(
        f"Load test: {args.concurrency} workers for {args.duration:.0f}s against {base_url} "
        f"({len(paths)} path(s))",
        flush=True,
    )

    results: list[tuple[int, float]] = []
    lock = threading.Lock()
    stop = threading.Event()
    deadline = time.monotonic() + args.duration

    threads = [
        threading.Thread(
            target=_worker,
            args=(base_url, paths, deadline, args.timeout, results, lock, stop),
            daemon=True,
        )
        for _ in range(args.concurrency)
    ]

    started = time.monotonic()
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        stop.set()
        print("\nInterrupted; reporting partial results.", file=sys.stderr)
    elapsed = max(time.monotonic() - started, 1e-9)

    total = len(results)
    if total == 0:
        print("No requests completed.", file=sys.stderr)
        return 1

    latencies = [seconds for _, seconds in results]
    status_counts: dict[str, int] = {}
    failures = 0
    for status, _ in results:
        key = str(status) if status else "transport_error"
        status_counts[key] = status_counts.get(key, 0) + 1
        if status == 0 or status >= 500:
            failures += 1

    error_rate = failures / total
    summary = {
        "base_url": base_url,
        "paths": paths,
        "duration_seconds": round(elapsed, 3),
        "concurrency": args.concurrency,
        "requests": total,
        "throughput_rps": round(total / elapsed, 2),
        "error_rate": round(error_rate, 4),
        "status_counts": status_counts,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies) * 1000, 2),
            "p50": round(_percentile(latencies, 0.50) * 1000, 2),
            "p95": round(_percentile(latencies, 0.95) * 1000, 2),
            "p99": round(_percentile(latencies, 0.99) * 1000, 2),
            "max": round(max(latencies) * 1000, 2),
        },
    }

    print(json.dumps(summary, indent=2))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
        print(f"Wrote {args.json_path}")

    if error_rate > args.max_error_rate:
        print(
            f"FAIL: error rate {error_rate:.2%} exceeds {args.max_error_rate:.2%}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
