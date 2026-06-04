"""In-memory request latency metrics for developer diagnostics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from math import ceil, floor
from threading import Lock


WINDOW_SIZE = 500


@dataclass
class EndpointWindow:
    """Rolling latency/status window for a single endpoint key."""

    method: str
    path: str
    durations_ms: deque[float] = field(default_factory=deque)
    statuses: deque[int] = field(default_factory=deque)
    status_2xx: int = 0
    status_3xx: int = 0
    status_4xx: int = 0
    status_5xx: int = 0

    def add(self, duration_ms: float, status: int, window_size: int) -> None:
        """Add a new sample and evict the oldest one when over capacity."""
        if len(self.durations_ms) >= window_size:
            old_status = self.statuses.popleft()
            self.durations_ms.popleft()
            self._dec_status_bucket(old_status)

        self.durations_ms.append(duration_ms)
        self.statuses.append(status)
        self._inc_status_bucket(status)

    def _inc_status_bucket(self, status: int) -> None:
        if 200 <= status <= 299:
            self.status_2xx += 1
        elif 300 <= status <= 399:
            self.status_3xx += 1
        elif 400 <= status <= 499:
            self.status_4xx += 1
        elif 500 <= status <= 599:
            self.status_5xx += 1

    def _dec_status_bucket(self, status: int) -> None:
        if 200 <= status <= 299:
            self.status_2xx = max(0, self.status_2xx - 1)
        elif 300 <= status <= 399:
            self.status_3xx = max(0, self.status_3xx - 1)
        elif 400 <= status <= 499:
            self.status_4xx = max(0, self.status_4xx - 1)
        elif 500 <= status <= 599:
            self.status_5xx = max(0, self.status_5xx - 1)


class RequestMetricsCollector:
    """Thread-safe in-memory collector for endpoint latency windows."""

    def __init__(self, window_size: int = WINDOW_SIZE):
        self.window_size = window_size
        self._lock = Lock()
        self._windows: dict[str, EndpointWindow] = {}

    def record(self, method: str, path: str, status: int | None, duration_ms: float) -> None:
        """Record one request sample."""
        safe_status = int(status or 500)
        key = f"{method} {path}"

        with self._lock:
            window = self._windows.get(key)
            if window is None:
                window = EndpointWindow(method=method, path=path)
                self._windows[key] = window
            window.add(duration_ms=duration_ms, status=safe_status, window_size=self.window_size)

    def reset(self) -> None:
        """Clear all collected request metrics."""
        with self._lock:
            self._windows.clear()

    def snapshot(self, sort_by: str = "p95_ms", limit: int = 200) -> dict:
        """Return a sorted snapshot of all endpoint metrics."""
        with self._lock:
            rows = [self._serialize_window(window) for window in self._windows.values()]

        sort_key = sort_by if rows and sort_by in rows[0] else "p95_ms"
        rows.sort(key=lambda row: float(row.get(sort_key, 0.0)), reverse=True)
        if limit > 0:
            rows = rows[:limit]

        total_requests = sum(row["count"] for row in rows)
        return {
            "generated_at": datetime.now().isoformat(),
            "window_size": self.window_size,
            "total_requests_in_window": total_requests,
            "endpoint_count": len(rows),
            "endpoints": rows,
        }

    def _serialize_window(self, window: EndpointWindow) -> dict:
        durations = list(window.durations_ms)
        count = len(durations)
        if count == 0:
            return {
                "method": window.method,
                "path": window.path,
                "count": 0,
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p90_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_ms": 0.0,
                "status_2xx": 0,
                "status_3xx": 0,
                "status_4xx": 0,
                "status_5xx": 0,
            }

        durations.sort()
        avg_ms = sum(durations) / count
        return {
            "method": window.method,
            "path": window.path,
            "count": count,
            "avg_ms": round(avg_ms, 1),
            "p50_ms": round(_percentile(durations, 50), 1),
            "p90_ms": round(_percentile(durations, 90), 1),
            "p95_ms": round(_percentile(durations, 95), 1),
            "p99_ms": round(_percentile(durations, 99), 1),
            "max_ms": round(durations[-1], 1),
            "status_2xx": window.status_2xx,
            "status_3xx": window.status_3xx,
            "status_4xx": window.status_4xx,
            "status_5xx": window.status_5xx,
        }


def _percentile(sorted_values: list[float], percentile: int) -> float:
    """Linear interpolation percentile on a sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    idx = (len(sorted_values) - 1) * (percentile / 100.0)
    low = floor(idx)
    high = ceil(idx)
    if low == high:
        return sorted_values[low]
    weight = idx - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


_collector = RequestMetricsCollector()


def get_request_metrics_collector() -> RequestMetricsCollector:
    """Return the process-global request metrics collector."""
    return _collector

