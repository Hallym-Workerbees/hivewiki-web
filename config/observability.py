import platform
import threading
import time
from importlib import metadata

from django.core.cache import cache
from django.db import connections
from django.db.utils import DatabaseError
from django.http import HttpResponse

PROCESS_START_TIME = time.time()
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
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

try:
    APP_VERSION = metadata.version("hivewiki-web")
except metadata.PackageNotFoundError:
    APP_VERSION = "0.1.0"


_metrics_lock = threading.Lock()
_http_requests_total = {}
_http_responses_total = {}
_http_request_duration_seconds = {}


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
    checks = run_readiness_checks()
    return HttpResponse(render_metrics(checks), content_type=PROMETHEUS_CONTENT_TYPE)


def record_http_request(method, route, status_code, duration_seconds):
    request_key = (method, route)
    response_key = (method, route, str(status_code))

    with _metrics_lock:
        _http_requests_total[request_key] = _http_requests_total.get(request_key, 0) + 1
        _http_responses_total[response_key] = (
            _http_responses_total.get(response_key, 0) + 1
        )

        bucket_counts, total_sum, total_count = _http_request_duration_seconds.get(
            request_key,
            ({bucket: 0 for bucket in REQUEST_DURATION_BUCKETS}, 0.0, 0),
        )
        for bucket in REQUEST_DURATION_BUCKETS:
            if duration_seconds <= bucket:
                bucket_counts[bucket] += 1
        _http_request_duration_seconds[request_key] = (
            bucket_counts,
            total_sum + duration_seconds,
            total_count + 1,
        )


def reset_metrics():
    with _metrics_lock:
        _http_requests_total.clear()
        _http_responses_total.clear()
        _http_request_duration_seconds.clear()


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


def render_metrics(checks):
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
            "# HELP hivewiki_http_requests_total Total number of HTTP requests received.",
            "# TYPE hivewiki_http_requests_total counter",
        ]
    )

    with _metrics_lock:
        request_items = sorted(_http_requests_total.items())
        response_items = sorted(_http_responses_total.items())
        duration_items = sorted(_http_request_duration_seconds.items())

    for (method, route), count in request_items:
        labels = _format_labels(method=method, route=route)
        lines.append(f"hivewiki_http_requests_total{labels} {count}")

    lines.extend(
        [
            "# HELP hivewiki_http_responses_total Total number of HTTP responses sent.",
            "# TYPE hivewiki_http_responses_total counter",
        ]
    )
    for (method, route, status_code), count in response_items:
        labels = _format_labels(method=method, route=route, status_code=status_code)
        lines.append(f"hivewiki_http_responses_total{labels} {count}")

    lines.extend(
        [
            "# HELP hivewiki_http_request_duration_seconds HTTP request latency in seconds.",
            "# TYPE hivewiki_http_request_duration_seconds histogram",
        ]
    )
    for (method, route), (bucket_counts, total_sum, total_count) in duration_items:
        labels = _format_labels(method=method, route=route)
        for bucket in REQUEST_DURATION_BUCKETS:
            bucket_labels = _format_labels(method=method, route=route, le=str(bucket))
            lines.append(
                "hivewiki_http_request_duration_seconds_bucket"
                f"{bucket_labels} {bucket_counts[bucket]}"
            )
        inf_labels = _format_labels(method=method, route=route, le="+Inf")
        lines.append(
            f"hivewiki_http_request_duration_seconds_bucket{inf_labels} {total_count}"
        )
        lines.append(
            f"hivewiki_http_request_duration_seconds_sum{labels} {total_sum:.6f}"
        )
        lines.append(
            f"hivewiki_http_request_duration_seconds_count{labels} {total_count}"
        )

    return "\n".join(lines) + "\n"


def get_route_label(request):
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match and resolver_match.route:
        route = f"/{resolver_match.route}"
        return route if route.startswith("/") else f"/{route}"

    path = request.path_info or "/"
    return path if path.startswith("/") else f"/{path}"


def _format_labels(**labels):
    formatted = ",".join(
        f'{key}="{_escape_label_value(value)}"' for key, value in labels.items()
    )
    return "{" + formatted + "}"


def _escape_label_value(value):
    return str(value).replace("\\", r"\\").replace('"', r"\"").replace("\n", r"\n")
