import contextvars
import json
import logging
import time
import uuid
from datetime import UTC, datetime

from django.utils.deprecation import MiddlewareMixin

_request_context: contextvars.ContextVar[dict[str, object] | None] = (
    contextvars.ContextVar(
        "request_context",
        default=None,
    )
)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def set_request_context(**kwargs) -> None:
    context = dict(_request_context.get() or {})
    context.update({key: value for key, value in kwargs.items() if value is not None})
    _request_context.set(context)


def clear_request_context() -> None:
    _request_context.set(None)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _request_context.get() or {}
        for field in (
            "request_id",
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


class RequestLoggingMiddleware(MiddlewareMixin):
    logger = logging.getLogger("hivewiki.request")

    def __call__(self, request):
        started_at = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.request_id = request_id

        user = getattr(request, "user", None)
        user_id = user.pk if getattr(user, "is_authenticated", False) else None
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        remote_addr = forwarded_for.split(",")[0].strip() or request.META.get(
            "REMOTE_ADDR"
        )
        set_request_context(
            request_id=request_id,
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
            clear_request_context()
            raise

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        user = getattr(request, "user", None)
        user_id = user.pk if getattr(user, "is_authenticated", False) else None
        set_request_context(
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
        )
        self.logger.info("request_complete")
        response["X-Request-ID"] = request_id
        clear_request_context()
        return response
