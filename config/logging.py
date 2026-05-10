import contextvars
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings

from config.observability import get_route_label, record_http_request

_request_context: contextvars.ContextVar[dict[str, object] | None] = (
    contextvars.ContextVar(
        "request_context",
        default=None,
    )
)
HEALTHCHECK_PATHS = frozenset(("/livez/", "/readyz/"))
ACCESS_LOGGER_NAMES = frozenset(("django.server", "hivewiki.request", "uvicorn.access"))


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def begin_request_context() -> contextvars.Token:
    return _request_context.set({})


def set_request_context(**kwargs) -> None:
    context = dict(_request_context.get() or {})
    context.update({key: value for key, value in kwargs.items() if value is not None})
    _request_context.set(context)


def _normalize_path(path: str | None) -> str:
    normalized_path = urlsplit(path or "").path or "/"
    if normalized_path != "/" and not normalized_path.endswith("/"):
        normalized_path = f"{normalized_path}/"
    return normalized_path


def is_healthcheck_path(path: str | None) -> bool:
    return _normalize_path(path) in HEALTHCHECK_PATHS


def should_log_healthcheck_requests() -> bool:
    return getattr(settings, "DJANGO_LOG_HEALTHCHECKS", False)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _request_context.get() or {}
        for field in (
            "request_id",
            "upstream_request_id",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "user_id",
            "remote_addr",
        ):
            setattr(record, field, context.get(field))
        return True


class SuppressHealthcheckAccessLogsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if should_log_healthcheck_requests():
            return True

        if record.name not in ACCESS_LOGGER_NAMES:
            return True

        path = self._get_path(record)
        if not is_healthcheck_path(path):
            return True

        if record.name == "hivewiki.request":
            return record.getMessage() != "request_complete"

        return False

    def _get_path(self, record: logging.LogRecord) -> str | None:
        path = getattr(record, "path", None)
        if path:
            return path

        if record.name == "uvicorn.access":
            return self._get_uvicorn_access_path(record)

        if record.name == "django.server":
            return self._get_django_server_path(record)

        return None

    def _get_uvicorn_access_path(self, record: logging.LogRecord) -> str | None:
        args = getattr(record, "args", ())
        if len(args) < 3:
            return None
        return str(args[2])

    def _get_django_server_path(self, record: logging.LogRecord) -> str | None:
        args = getattr(record, "args", ())
        if not args:
            return None

        request_line = str(args[0])
        parts = request_line.split()
        if len(parts) < 2:
            return None
        return parts[1]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload = {
            "timestamp": _utc_timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "module": record.module,
            "line": record.lineno,
            "request_id": getattr(record, "request_id", None),
            "upstream_request_id": getattr(record, "upstream_request_id", None),
            "method": getattr(record, "method", None),
            "path": getattr(record, "path", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "user_id": getattr(record, "user_id", None),
            "remote_addr": getattr(record, "remote_addr", None),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _get_remote_addr(request) -> str:
    header_name = settings.CLIENT_IP_HEADER
    if header_name:
        raw_value = request.META.get(header_name, "")
        if raw_value:
            return raw_value.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _get_authenticated_user_id(request):
    current_user = getattr(request, "current_user", None)
    if current_user is not None:
        return getattr(current_user, "pk", None)

    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return user.pk

    return None


class RequestLoggingMiddleware:
    logger = logging.getLogger("hivewiki.request")

    def __init__(self, get_response):
        self.get_response = get_response
        self._async_mode = iscoroutinefunction(get_response)
        if self._async_mode:
            markcoroutinefunction(self)

    def _begin_request(self, request):
        started_at = time.perf_counter()
        request_context_token = begin_request_context()
        request_id = str(uuid.uuid4())
        upstream_request_id = request.headers.get("X-Request-ID", "").strip() or None
        request.request_id = request_id

        user_id = _get_authenticated_user_id(request)
        remote_addr = _get_remote_addr(request)
        set_request_context(
            request_id=request_id,
            upstream_request_id=upstream_request_id,
            method=request.method,
            path=request.get_full_path(),
            user_id=user_id,
            remote_addr=remote_addr,
        )
        return started_at, request_context_token, request_id

    def _log_exception(self, request, started_at):
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        set_request_context(status_code=500, duration_ms=duration_ms)
        record_http_request(
            method=request.method,
            route=get_route_label(request),
            status_code=500,
            duration_seconds=duration_ms / 1000,
        )
        self.logger.exception("request_failed")

    def _log_response(self, request, response, started_at, request_id):
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        duration_seconds = duration_ms / 1000
        user_id = _get_authenticated_user_id(request)
        set_request_context(
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
        )
        record_http_request(
            method=request.method,
            route=get_route_label(request),
            status_code=response.status_code,
            duration_seconds=duration_seconds,
        )
        if should_log_healthcheck_requests() or not is_healthcheck_path(
            request.path_info
        ):
            self.logger.info("request_complete")
        response["X-Request-ID"] = request_id
        return response

    def __call__(self, request):
        if self._async_mode:
            return self.__acall__(request)

        started_at, request_context_token, request_id = self._begin_request(request)

        try:
            response = self.get_response(request)
        except Exception:
            self._log_exception(request, started_at)
            raise
        else:
            return self._log_response(
                request=request,
                response=response,
                started_at=started_at,
                request_id=request_id,
            )
        finally:
            _request_context.reset(request_context_token)

    async def __acall__(self, request):
        started_at, request_context_token, request_id = self._begin_request(request)

        try:
            response = await self.get_response(request)
        except Exception:
            self._log_exception(request, started_at)
            raise
        else:
            return self._log_response(
                request=request,
                response=response,
                started_at=started_at,
                request_id=request_id,
            )
        finally:
            _request_context.reset(request_context_token)
