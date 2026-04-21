import math
import time

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache

from .models import HiveUser, UserStatus

SESSION_USER_ID_KEY = "hivewiki_user_id"


def _normalize_identifier(value: str) -> str:
    return (value or "").strip().lower() or "anonymous"


def get_client_ip(request) -> str:
    header_name = settings.CLIENT_IP_HEADER
    if header_name:
        raw_value = request.META.get(header_name, "")
        if raw_value:
            return raw_value.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _login_rate_limit_key(*, email: str, client_ip: str) -> str:
    return f"login_attempt:{client_ip}:{_normalize_identifier(email)}"


def _get_login_rate_limit_state(*, email: str, client_ip: str) -> dict:
    return cache.get(_login_rate_limit_key(email=email, client_ip=client_ip), {})


def _remaining_timeout_seconds(expires_at: float) -> int:
    return max(1, math.ceil(expires_at - time.time()))


def is_login_rate_limited(*, email: str, client_ip: str) -> bool:
    state = _get_login_rate_limit_state(email=email, client_ip=client_ip)
    attempts = int(state.get("attempts", 0))
    return attempts >= settings.LOGIN_RATE_LIMIT_ATTEMPTS


def get_login_rate_limit_remaining_seconds(*, email: str, client_ip: str) -> int:
    state = _get_login_rate_limit_state(email=email, client_ip=client_ip)
    expires_at = state.get("expires_at")
    if not expires_at:
        return 0
    return max(0, math.ceil(expires_at - time.time()))


def format_rate_limit_wait_time(seconds: int) -> str:
    if seconds <= 0:
        return "잠시"
    if seconds < 60:
        return f"약 {seconds}초"
    minutes = math.ceil(seconds / 60)
    return f"약 {minutes}분"


def record_failed_login(*, email: str, client_ip: str) -> int:
    key = _login_rate_limit_key(email=email, client_ip=client_ip)
    window_seconds = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    state = _get_login_rate_limit_state(email=email, client_ip=client_ip)
    expires_at = state.get("expires_at")
    attempts = int(state.get("attempts", 0))

    if not expires_at or expires_at <= time.time():
        expires_at = time.time() + window_seconds
        attempts = 0

    attempts += 1
    timeout = _remaining_timeout_seconds(expires_at)
    cache.set(
        key,
        {
            "attempts": attempts,
            "expires_at": expires_at,
        },
        timeout=timeout,
    )
    return attempts


def reset_login_rate_limit(*, email: str, client_ip: str) -> None:
    cache.delete(_login_rate_limit_key(email=email, client_ip=client_ip))


def create_user(*, username: str, email: str, password: str) -> HiveUser:
    return HiveUser.objects.create(
        username=username,
        email=email,
        password_hash=make_password(password),
        status=UserStatus.ACTIVE,
    )


def authenticate_user(*, email: str, password: str) -> HiveUser | None:
    user = (
        HiveUser.objects.filter(email__iexact=email, status=UserStatus.ACTIVE)
        .only("id", "username", "email", "password_hash", "status")
        .first()
    )
    if not user or not user.password_hash:
        return None
    if not check_password(password, user.password_hash):
        return None
    return user


def login_user(request, user: HiveUser) -> None:
    request.session.flush()
    request.session[SESSION_USER_ID_KEY] = str(user.id)
    request.session.cycle_key()


def logout_user(request) -> None:
    request.session.flush()


def update_user_password(*, user: HiveUser, new_password: str) -> HiveUser:
    user.password_hash = make_password(new_password)
    user.save(update_fields=["password_hash", "updated_at"])
    return user


def get_current_user(request) -> HiveUser | None:
    cached_user = getattr(request, "_cached_hivewiki_user", None)
    if cached_user is not None:
        return cached_user

    user_id = request.session.get(SESSION_USER_ID_KEY)
    if not user_id:
        request._cached_hivewiki_user = None
        return None

    user = (
        HiveUser.objects.filter(id=user_id, status=UserStatus.ACTIVE)
        .only("id", "username", "email", "role", "status")
        .first()
    )
    request._cached_hivewiki_user = user
    return user
