import math
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from json import loads

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from .models import HiveUser, OAuthAccount, OAuthProvider, UserStatus

SESSION_USER_ID_KEY = "hivewiki_user_id"
OAUTH_STATE_SESSION_KEY = "oauth_state"


@dataclass(frozen=True)
class OAuthProviderConfig:
    provider: str
    label: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    scope: str


class OAuthError(Exception):
    pass


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


def _oauth_provider_configs() -> dict[str, OAuthProviderConfig]:
    return {
        OAuthProvider.GOOGLE: OAuthProviderConfig(
            provider=OAuthProvider.GOOGLE,
            label="Google",
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scope="openid email profile",
        ),
        OAuthProvider.GITHUB: OAuthProviderConfig(
            provider=OAuthProvider.GITHUB,
            label="GitHub",
            client_id=settings.GITHUB_OAUTH_CLIENT_ID,
            client_secret=settings.GITHUB_OAUTH_CLIENT_SECRET,
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            scope="read:user user:email",
        ),
    }


def get_available_oauth_providers(
    request, *, next_url: str = ""
) -> list[dict[str, str]]:
    providers = []
    for provider, config in _oauth_provider_configs().items():
        if not config.client_id or not config.client_secret:
            continue
        start_url = reverse("oauth_start", kwargs={"provider": provider})
        if next_url:
            start_url = f"{start_url}?{urllib.parse.urlencode({'next': next_url})}"
        providers.append(
            {
                "provider": provider,
                "label": config.label,
                "start_url": start_url,
            }
        )
    return providers


def get_oauth_provider_config(provider: str) -> OAuthProviderConfig:
    try:
        config = _oauth_provider_configs()[provider]
    except KeyError as exc:
        raise OAuthError("지원하지 않는 OAuth provider입니다.") from exc

    if not config.client_id or not config.client_secret:
        raise OAuthError(f"{config.label} OAuth 설정이 아직 완료되지 않았습니다.")
    return config


def _oauth_callback_url(request, provider: str) -> str:
    path = reverse("oauth_callback", kwargs={"provider": provider})
    return request.build_absolute_uri(path)


def begin_oauth_flow(request, *, provider: str, next_url: str = "") -> str:
    config = get_oauth_provider_config(provider)
    state = secrets.token_urlsafe(32)
    request.session[OAUTH_STATE_SESSION_KEY] = {
        "provider": provider,
        "state": state,
        "next_url": next_url,
    }
    params = {
        "client_id": config.client_id,
        "redirect_uri": _oauth_callback_url(request, provider),
        "response_type": "code",
        "scope": config.scope,
        "state": state,
    }
    if provider == OAuthProvider.GOOGLE:
        params["access_type"] = "offline"
        params["prompt"] = "select_account"
    return f"{config.authorize_url}?{urllib.parse.urlencode(params)}"


def _read_json_response(response) -> dict:
    return loads(response.read().decode("utf-8"))


def _post_form(url: str, data: dict, headers: dict[str, str] | None = None) -> dict:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers=headers or {},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return _read_json_response(response)


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict | list:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        return _read_json_response(response)


def _github_primary_email(access_token: str) -> str | None:
    emails = _get_json(
        "https://api.github.com/user/emails",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    for email_info in emails:
        if email_info.get("primary") and email_info.get("verified"):
            return email_info.get("email")
    for email_info in emails:
        if email_info.get("verified"):
            return email_info.get("email")
    return None


def exchange_oauth_code_for_profile(
    request, *, provider: str, code: str, state: str
) -> tuple[dict, str]:
    session_state = request.session.get(OAUTH_STATE_SESSION_KEY) or {}
    if session_state.get("provider") != provider or session_state.get("state") != state:
        raise OAuthError("OAuth state 검증에 실패했습니다. 다시 시도해 주세요.")

    config = get_oauth_provider_config(provider)
    callback_url = _oauth_callback_url(request, provider)

    try:
        token_response = _post_form(
            config.token_url,
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise OAuthError("OAuth 토큰 교환에 실패했습니다.") from exc

    access_token = token_response.get("access_token")
    if not access_token:
        raise OAuthError("OAuth access token을 받지 못했습니다.")

    try:
        if provider == OAuthProvider.GOOGLE:
            profile = _get_json(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            email = profile.get("email")
            if not email or not profile.get("email_verified"):
                raise OAuthError("Google 계정에서 검증된 이메일을 확인할 수 없습니다.")
            oauth_profile = {
                "provider_user_id": profile.get("sub"),
                "email": email.lower(),
                "provider_email": email.lower(),
                "username_hint": profile.get("given_name")
                or profile.get("name")
                or email.split("@")[0],
            }
        else:
            profile = _get_json(
                "https://api.github.com/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            email = (
                profile.get("email") or _github_primary_email(access_token) or ""
            ).lower()
            if not email:
                raise OAuthError("GitHub 계정에서 검증된 이메일을 확인할 수 없습니다.")
            oauth_profile = {
                "provider_user_id": str(profile.get("id")),
                "email": email,
                "provider_email": email,
                "username_hint": profile.get("login") or email.split("@")[0],
            }
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise OAuthError("OAuth 사용자 정보를 가져오지 못했습니다.") from exc

    request.session.pop(OAUTH_STATE_SESSION_KEY, None)
    return oauth_profile, session_state.get("next_url", "")


def _build_unique_username(base_value: str) -> str:
    normalized = "".join(
        ch for ch in (base_value or "user") if ch.isalnum() or ch == "_"
    )
    normalized = normalized.lower()[:16] or "user"
    candidate = normalized
    suffix = 1
    while HiveUser.objects.filter(username__iexact=candidate).exists():
        suffix_text = str(suffix)
        candidate = f"{normalized[: max(1, 16 - len(suffix_text))]}{suffix_text}"
        suffix += 1
    return candidate


def get_or_create_user_from_oauth_profile(*, provider: str, profile: dict) -> HiveUser:
    provider_user_id = profile["provider_user_id"]
    email = profile["email"]
    provider_email = profile.get("provider_email")

    oauth_account = (
        OAuthAccount.objects.select_related("user")
        .filter(provider=provider, provider_user_id=provider_user_id)
        .first()
    )
    if oauth_account:
        if oauth_account.user.status != UserStatus.ACTIVE:
            raise OAuthError("현재 계정 상태로는 소셜 로그인을 사용할 수 없습니다.")
        oauth_account.provider_email = provider_email
        oauth_account.last_login_at = timezone.now()
        oauth_account.save(update_fields=["provider_email", "last_login_at"])
        return oauth_account.user

    user = HiveUser.objects.filter(email__iexact=email).first()
    if user is not None and user.status != UserStatus.ACTIVE:
        raise OAuthError("현재 계정 상태로는 소셜 로그인을 사용할 수 없습니다.")
    if user is None:
        user = HiveUser.objects.create(
            username=_build_unique_username(
                profile.get("username_hint", email.split("@")[0])
            ),
            email=email,
            password_hash=None,
            status=UserStatus.ACTIVE,
        )

    OAuthAccount.objects.create(
        user=user,
        provider=provider,
        provider_user_id=provider_user_id,
        provider_email=provider_email,
        last_login_at=timezone.now(),
    )
    return user
