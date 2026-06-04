"""
Slowtrace middleware for diagnosing slow API requests.

Logs detailed diagnostics for any request exceeding a configurable threshold.
Normal requests get a standard one-line log. Slow requests get a full trace
with everything needed to investigate the bottleneck.
"""
import asyncio
import time
import threading
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from core.logging import get_logger
from core.profile_context import get_current_profile
from core.request_metrics import get_request_metrics_collector

log = get_logger(__name__)

# Threshold in ms - requests slower than this get a detailed trace
SLOW_THRESHOLD_MS = 500

# Paths to skip logging entirely (noisy/polling endpoints)
SKIP_PATHS = frozenset(("/", "/ws", "/api/processing/stats", "/api/media"))
SKIP_PREFIXES = ("/thumbnails/", "/thumbnail", "/file")


class SlowtraceMiddleware(BaseHTTPMiddleware):
    """Middleware that logs detailed diagnostics for slow requests."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        skip_logging = path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES)
        metric_path = _resolve_metric_path(request)

        start_time = time.monotonic()
        start_wall = time.time()

        profile_id = None
        query_string = None
        content_length = None
        content_type = None
        loop = None
        pending_tasks = None
        active_threads = None
        if not skip_logging:
            # Capture pre-request state for detailed slow traces.
            profile_id = _safe_get_profile()
            query_string = str(request.url.query) if request.url.query else None
            content_length = request.headers.get("content-length")
            content_type = request.headers.get("content-type")

            # Track the event loop - if it's blocked, asyncio tasks pile up.
            loop = asyncio.get_running_loop()
            pending_tasks = len(asyncio.all_tasks(loop))

            # Track active threads (high count suggests thread pool contention).
            active_threads = threading.active_count()

        # Execute the request
        error = None
        status_code = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error = exc
            status_code = 500
            raise
        finally:
            duration_ms = (time.monotonic() - start_time) * 1000
            get_request_metrics_collector().record(
                method=method,
                path=metric_path,
                status=status_code,
                duration_ms=duration_ms,
            )

            if not skip_logging:
                if duration_ms >= SLOW_THRESHOLD_MS:
                    # Slow request - emit detailed trace
                    post_tasks = len(asyncio.all_tasks(loop))
                    post_threads = threading.active_count()

                    details = {
                        "method": method,
                        "path": path,
                        "status": status_code,
                        "duration_ms": round(duration_ms, 1),
                        "profile_id": profile_id,
                        "query": query_string,
                        "content_length": content_length,
                        "content_type": content_type,
                        "wall_start": _format_time(start_wall),
                        "asyncio_tasks_before": pending_tasks,
                        "asyncio_tasks_after": post_tasks,
                        "threads_before": active_threads,
                        "threads_after": post_threads,
                    }

                    if error:
                        details["error"] = str(error)
                        details["error_type"] = type(error).__name__

                    log.warning("SLOWTRACE", **details)
                else:
                    # Normal request - one-line log
                    log.info(
                        "http request",
                        method=method,
                        path=path,
                        status=status_code,
                        duration_ms=round(duration_ms, 1),
                    )


def _safe_get_profile() -> str | None:
    """Get current profile without raising."""
    try:
        return get_current_profile()
    except Exception:
        return None


def _format_time(t: float) -> str:
    """Format a timestamp as HH:MM:SS.mmm for log readability."""
    import datetime
    dt = datetime.datetime.fromtimestamp(t)
    return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _resolve_metric_path(request: Request) -> str:
    """Resolve normalized route path for metric aggregation."""
    route = request.scope.get("route")
    if route:
        path = getattr(route, "path", None) or getattr(route, "path_format", None)
        if path:
            return str(path)
    return request.url.path
