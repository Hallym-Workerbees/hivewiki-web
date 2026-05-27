import os
import platform
import threading
import time
from importlib import metadata

from django.core.cache import cache
from django.db import connections
from django.db.utils import DatabaseError
from django.http import HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Histogram,
    generate_latest,
)

try:
    from prometheus_client import CollectorRegistry, multiprocess
except ImportError:  # pragma: no cover
    CollectorRegistry = None
    multiprocess = None

PROCESS_START_TIME = time.time()
METRICS_READINESS_CACHE_TTL_SECONDS = 15
REQUEST_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)
EXCLUDED_REQUEST_METRIC_ROUTES = frozenset(("/livez/", "/readyz/", "/metrics/"))

try:
    APP_VERSION = metadata.version("hivewiki-web")
except metadata.PackageNotFoundError:
    APP_VERSION = "0.1.0"


_metrics_lock = threading.Lock()
_registered_collectors = []
_http_requests_total = None
_http_responses_total = None
_http_request_duration_seconds = None

_readiness_cache_lock = threading.Lock()
_readiness_cache_checks = None
_readiness_cache_expires_at = 0.0


def _initialize_metrics():
    global _http_request_duration_seconds
    global _http_requests_total
    global _http_responses_total

    with _metrics_lock:
        for collector in _registered_collectors:
            try:
                REGISTRY.unregister(collector)
            except KeyError:
                continue
        _registered_collectors.clear()

        _http_requests_total = Counter(
            "hivewiki_http_requests_total",
            "Total number of HTTP requests received.",
            ("method", "route"),
        )
        _http_responses_total = Counter(
            "hivewiki_http_responses_total",
            "Total number of HTTP responses sent.",
            ("method", "route", "status_code"),
        )
        _http_request_duration_seconds = Histogram(
            "hivewiki_http_request_duration_seconds",
            "HTTP request latency in seconds.",
            ("method", "route"),
            buckets=REQUEST_DURATION_BUCKETS,
        )
        _registered_collectors.extend(
            [
                _http_requests_total,
                _http_responses_total,
                _http_request_duration_seconds,
            ]
        )


_initialize_metrics()


def liveness_probe(_request):
    return HttpResponse("ok\n", content_type="text/plain")


def readiness_probe(_request):
    checks = run_readiness_checks()
    failed_checks = [name for name, ok in checks.items() if not ok]
    if failed_checks:
        body = "not ready: " + ", ".join(failed_checks) + "\n"
        return HttpResponse(body, content_type="text/plain", status=503)

    return HttpResponse("ready\n", content_type="text/plain")


def metrics_view(_request):
    checks = get_cached_readiness_checks()
    content = render_runtime_metrics(checks) + get_http_metrics_output()
    return HttpResponse(content, content_type=CONTENT_TYPE_LATEST)


def record_http_request(method, route, status_code, duration_seconds):
    if route in EXCLUDED_REQUEST_METRIC_ROUTES:
        return

    _http_requests_total.labels(method=method, route=route).inc()
    _http_responses_total.labels(
        method=method,
        route=route,
        status_code=str(status_code),
    ).inc()
    _http_request_duration_seconds.labels(method=method, route=route).observe(
        duration_seconds
    )


def reset_metrics():
    global _readiness_cache_checks
    global _readiness_cache_expires_at

    _initialize_metrics()
    with _readiness_cache_lock:
        _readiness_cache_checks = None
        _readiness_cache_expires_at = 0.0


def get_cached_readiness_checks():
    global _readiness_cache_checks
    global _readiness_cache_expires_at

    now = time.monotonic()
    with _readiness_cache_lock:
        if _readiness_cache_checks is not None and now < _readiness_cache_expires_at:
            return dict(_readiness_cache_checks)

    checks = run_readiness_checks()
    with _readiness_cache_lock:
        _readiness_cache_checks = dict(checks)
        _readiness_cache_expires_at = now + METRICS_READINESS_CACHE_TTL_SECONDS
    return checks


def run_readiness_checks():
    return {
        "database": check_database(),
        "cache": check_cache(),
    }


def check_database():
    try:
        connection = connections["default"]
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return False

    return True


def check_cache():
    key = "hivewiki:healthcheck:ready"
    value = str(time.time())

    try:
        cache.set(key, value, timeout=30)
        cached_value = cache.get(key)
        cache.delete(key)
    except Exception:
        return False

    return cached_value == value


def render_runtime_metrics(checks):
    lines = [
        "# HELP hivewiki_up Whether the Django process is running.",
        "# TYPE hivewiki_up gauge",
        "hivewiki_up 1",
        "# HELP hivewiki_process_start_time_seconds Start time of the Django process since unix epoch in seconds.",
        "# TYPE hivewiki_process_start_time_seconds gauge",
        f"hivewiki_process_start_time_seconds {PROCESS_START_TIME:.6f}",
        "# HELP hivewiki_build_info Static build and runtime information.",
        "# TYPE hivewiki_build_info gauge",
        (
            f'hivewiki_build_info{{version="{APP_VERSION}",'
            f'python_version="{platform.python_version()}"}} 1'
        ),
        "# HELP hivewiki_readiness_check Whether each readiness dependency is healthy.",
        "# TYPE hivewiki_readiness_check gauge",
    ]

    for name, ok in checks.items():
        lines.append(f'hivewiki_readiness_check{{check="{name}"}} {1 if ok else 0}')

    overall_ready = 1 if all(checks.values()) else 0
    lines.extend(
        [
            "# HELP hivewiki_ready Whether the application is ready to serve traffic.",
            "# TYPE hivewiki_ready gauge",
            f"hivewiki_ready {overall_ready}",
        ]
    )
    return "\n".join(lines) + "\n"


def get_http_metrics_output():
    registry = get_metrics_registry()
    return generate_latest(registry).decode("utf-8")


def get_metrics_registry():
    if multiprocess is None or CollectorRegistry is None:
        return REGISTRY

    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "").strip()
    if not multiproc_dir:
        return REGISTRY

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return registry


def get_route_label(request):
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match and resolver_match.route:
        route = f"/{resolver_match.route}"
        return route if route.startswith("/") else f"/{route}"

    path = request.path_info or "/"
    return path if path.startswith("/") else f"/{path}"
