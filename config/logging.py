import contextvars
import json
import logging
import time
import uuid
from datetime import UTC, datetime

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

_request_context: contextvars.ContextVar[dict[str, object] | None] = (
    contextvars.ContextVar(
        "request_context",
        default=None,
    )
)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def begin_request_context() -> contextvars.Token:
    return _request_context.set({})


def set_request_context(**kwargs) -> None:
    context = dict(_request_context.get() or {})
    context.update({key: value for key, value in kwargs.items() if value is not None})
    _request_context.set(context)


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


class RequestLoggingMiddleware(MiddlewareMixin):
    logger = logging.getLogger("hivewiki.request")

    def __call__(self, request):
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

        try:
            response = self.get_response(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            set_request_context(status_code=500, duration_ms=duration_ms)
            self.logger.exception("request_failed")
            raise
        else:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            user_id = _get_authenticated_user_id(request)
            set_request_context(
                status_code=response.status_code,
                duration_ms=duration_ms,
                user_id=user_id,
            )
            self.logger.info("request_complete")
            response["X-Request-ID"] = request_id
            return response
        finally:
            _request_context.reset(request_context_token)
