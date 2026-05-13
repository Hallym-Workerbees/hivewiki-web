import math
import mimetypes
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from importlib import import_module
from json import loads
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.core.signing import BadSignature, SignatureExpired
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from .models import HiveUser, OAuthAccount, OAuthProvider, UserStatus

SESSION_USER_ID_KEY = "hivewiki_user_id"
OAUTH_STATE_SESSION_KEY = "oauth_state"
TIMEZONE_SESSION_KEY = "django_timezone"
PENDING_OAUTH_CONFIRM_SESSION_KEY = "pending_oauth_confirm"
OAUTH_ACTION_LOGIN = "login"
OAUTH_ACTION_LINK = "link"
USER_SESSION_KEYS_PREFIX = "user_session_keys"
PENDING_OAUTH_CONFIRM_SALT = "accounts.pending_oauth_confirm"
PENDING_OAUTH_CONFIRM_MAX_AGE_SECONDS = 600
ALLOWED_PROFILE_IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)


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


class ProfileImageUploadError(Exception):
    pass


def inactive_account_message() -> str:
    return "이 계정은 비활성화되어 로그인할 수 없습니다. 관리자에게 문의해 주세요."


def _s3_upload_configured() -> bool:
    return bool(
        settings.AWS_S3_UPLOAD_BUCKET
        and settings.AWS_S3_UPLOAD_REGION
        and settings.AWS_S3_UPLOAD_PUBLIC_BASE_URL
    )


def _guess_content_type(filename: str) -> str:
    guessed_type, _ = mimetypes.guess_type(filename or "")
    return guessed_type or "application/octet-stream"


def _normalize_upload_content_type(*, filename: str, content_type: str) -> str:
    normalized_content_type = (content_type or "").strip().lower()
    guessed_content_type = _guess_content_type(filename).lower()

    if (
        normalized_content_type
        and normalized_content_type in ALLOWED_PROFILE_IMAGE_CONTENT_TYPES
    ):
        return normalized_content_type
    if guessed_content_type in ALLOWED_PROFILE_IMAGE_CONTENT_TYPES:
        return guessed_content_type
    raise ProfileImageUploadError("이미지 파일만 업로드할 수 있습니다.")


def _build_s3_upload_client():
    client_kwargs = {"region_name": settings.AWS_S3_UPLOAD_REGION}
    if settings.AWS_S3_UPLOAD_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = settings.AWS_S3_UPLOAD_ENDPOINT_URL
    if settings.AWS_S3_UPLOAD_ACCESS_KEY_ID:
        client_kwargs["aws_access_key_id"] = settings.AWS_S3_UPLOAD_ACCESS_KEY_ID
    if settings.AWS_S3_UPLOAD_SECRET_ACCESS_KEY:
        client_kwargs["aws_secret_access_key"] = (
            settings.AWS_S3_UPLOAD_SECRET_ACCESS_KEY
        )
    return boto3.client("s3", **client_kwargs)


def build_profile_image_upload_payload(
    *,
    user: HiveUser,
    filename: str,
    content_type: str,
) -> dict:
    if not _s3_upload_configured():
        raise ProfileImageUploadError("S3 업로드 설정이 아직 완료되지 않았습니다.")

    normalized_filename = (filename or "").strip()
    if not normalized_filename:
        raise ProfileImageUploadError("업로드할 파일 이름이 필요합니다.")

    content_type = _normalize_upload_content_type(
        filename=normalized_filename,
        content_type=content_type,
    )

    prefix = settings.AWS_S3_PROFILE_IMAGE_PREFIX.strip("/").replace("//", "/")
    file_extension = Path(normalized_filename).suffix.lower()[:10]
    object_key = (
        f"{prefix}/{user.id}/{secrets.token_urlsafe(16)}{file_extension}"
        if prefix
        else f"{user.id}/{secrets.token_urlsafe(16)}{file_extension}"
    )
    client = _build_s3_upload_client()
    try:
        payload = client.generate_presigned_post(
            Bucket=settings.AWS_S3_UPLOAD_BUCKET,
            Key=object_key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, 5 * 1024 * 1024],
            ],
            ExpiresIn=600,
        )
    except (BotoCoreError, ClientError) as exc:
        raise ProfileImageUploadError(
            "S3 업로드 서명을 생성하지 못했습니다. 설정을 확인해 주세요."
        ) from exc
    public_base_url = settings.AWS_S3_UPLOAD_PUBLIC_BASE_URL.rstrip("/")

    return {
        "upload_url": payload["url"],
        "fields": payload["fields"],
        "public_url": f"{public_base_url}/{object_key}",
        "max_file_size": 5 * 1024 * 1024,
    }


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


def get_active_user_by_email(email: str) -> HiveUser | None:
    return (
        HiveUser.objects.filter(email__iexact=email, status=UserStatus.ACTIVE)
        .only("id", "username", "email", "password_hash", "status")
        .first()
    )


def get_user_by_email(email: str) -> HiveUser | None:
    return (
        HiveUser.objects.filter(email__iexact=email)
        .only("id", "username", "email", "password_hash", "status")
        .first()
    )


def get_user_oauth_accounts(user: HiveUser):
    return user.oauth_accounts.order_by("provider", "-last_login_at")


def get_unlinked_oauth_providers(request, *, user: HiveUser) -> list[dict[str, str]]:
    linked_providers = set(user.oauth_accounts.values_list("provider", flat=True))
    providers = []
    for provider_info in get_available_oauth_providers(
        request,
        route_name="oauth_link_start",
    ):
        if provider_info["provider"] in linked_providers:
            continue
        providers.append(provider_info)
    return providers


def get_existing_oauth_account_for_profile(
    *, provider: str, profile: dict
) -> OAuthAccount | None:
    return (
        OAuthAccount.objects.select_related("user")
        .filter(
            provider=provider,
            provider_user_id=profile["provider_user_id"],
        )
        .first()
    )


def get_existing_user_for_oauth_email(profile: dict) -> HiveUser | None:
    return HiveUser.objects.filter(email__iexact=profile["email"]).first()


def build_pending_oauth_confirmation(
    *, provider: str, profile: dict, user_id, next_url: str
) -> str:
    return signing.dumps(
        {
            "provider": provider,
            "profile": profile,
            "user_id": str(user_id),
            "next_url": next_url,
        },
        salt=PENDING_OAUTH_CONFIRM_SALT,
    )


def read_pending_oauth_confirmation(signed_value: str) -> dict:
    try:
        return signing.loads(
            signed_value,
            salt=PENDING_OAUTH_CONFIRM_SALT,
            max_age=PENDING_OAUTH_CONFIRM_MAX_AGE_SECONDS,
        )
    except SignatureExpired as exc:
        raise OAuthError(
            "OAuth 계정 연결 확인 시간이 만료되었습니다. 다시 시도해 주세요."
        ) from exc
    except BadSignature as exc:
        raise OAuthError(
            "OAuth 계정 연결 확인 정보가 올바르지 않습니다. 다시 시도해 주세요."
        ) from exc


def _reset_session_preserving(request, *keys: str) -> None:
    preserved_values = {
        key: request.session.get(key)
        for key in keys
        if request.session.get(key) is not None
    }
    request.session.flush()
    for key, value in preserved_values.items():
        request.session[key] = value


def _user_session_index_cache_key(user_id) -> str:
    return f"{USER_SESSION_KEYS_PREFIX}:{user_id}"


def _get_session_store_class():
    engine = import_module(settings.SESSION_ENGINE)
    return engine.SessionStore


def _get_tracked_session_keys(*, user: HiveUser) -> set[str]:
    return {
        session_key
        for session_key in cache.get(_user_session_index_cache_key(user.id), [])
        if session_key
    }


def _store_tracked_session_keys(*, user: HiveUser, session_keys: set[str]) -> None:
    if not session_keys:
        cache.delete(_user_session_index_cache_key(user.id))
        return
    cache.set(
        _user_session_index_cache_key(user.id),
        sorted(session_keys),
        timeout=settings.SESSION_COOKIE_AGE,
    )


def register_user_session(*, request, user: HiveUser) -> None:
    session_key = request.session.session_key
    if not session_key:
        return
    session_keys = _get_tracked_session_keys(user=user)
    session_keys.add(session_key)
    _store_tracked_session_keys(user=user, session_keys=session_keys)


def unregister_user_session(*, request, user: HiveUser | None) -> None:
    session_key = request.session.session_key
    if user is None or not session_key:
        return
    session_keys = _get_tracked_session_keys(user=user)
    if session_key not in session_keys:
        return
    session_keys.remove(session_key)
    _store_tracked_session_keys(user=user, session_keys=session_keys)


def purge_user_sessions(*, user: HiveUser) -> None:
    session_keys = _get_tracked_session_keys(user=user)
    if not session_keys:
        return
    session_store_class = _get_session_store_class()
    for session_key in session_keys:
        session_store = session_store_class(session_key=session_key)
        if not session_store.exists(session_key):
            continue
        session_store.delete()
    cache.delete(_user_session_index_cache_key(user.id))


def login_user(request, user: HiveUser) -> None:
    _reset_session_preserving(request, TIMEZONE_SESSION_KEY)
    request.session[SESSION_USER_ID_KEY] = str(user.id)
    request.session.cycle_key()
    register_user_session(request=request, user=user)


def logout_user(request) -> None:
    unregister_user_session(request=request, user=get_current_user(request))
    _reset_session_preserving(request, TIMEZONE_SESSION_KEY)


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


def set_browser_timezone(request, timezone_name: str) -> bool:
    normalized_timezone = (timezone_name or "").strip()
    if not normalized_timezone:
        return False

    try:
        ZoneInfo(normalized_timezone)
    except ZoneInfoNotFoundError:
        return False

    request.session[TIMEZONE_SESSION_KEY] = normalized_timezone
    return True


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
    request, *, next_url: str = "", route_name: str = "oauth_start"
) -> list[dict[str, str]]:
    providers = []
    for provider, config in _oauth_provider_configs().items():
        if not config.client_id or not config.client_secret:
            continue
        start_url = reverse(route_name, kwargs={"provider": provider})
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


def begin_oauth_flow(
    request,
    *,
    provider: str,
    next_url: str = "",
    action: str = OAUTH_ACTION_LOGIN,
    link_user: HiveUser | None = None,
) -> str:
    config = get_oauth_provider_config(provider)
    state = secrets.token_urlsafe(32)
    request.session[OAUTH_STATE_SESSION_KEY] = {
        "provider": provider,
        "state": state,
        "next_url": next_url,
        "action": action,
        "link_user_id": str(link_user.id) if link_user is not None else "",
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
) -> tuple[dict, dict]:
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
                "profile_image": (profile.get("picture") or "").strip(),
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
                "profile_image": (profile.get("avatar_url") or "").strip(),
                "username_hint": profile.get("login") or email.split("@")[0],
            }
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise OAuthError("OAuth 사용자 정보를 가져오지 못했습니다.") from exc

    request.session.pop(OAUTH_STATE_SESSION_KEY, None)
    return oauth_profile, session_state


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


def _sync_profile_image_from_oauth_profile(
    *, user: HiveUser, profile: dict
) -> HiveUser:
    profile_image = (profile.get("profile_image") or "").strip()
    if user.profile_image or not profile_image:
        return user
    user.profile_image = profile_image
    user.save(update_fields=["profile_image", "updated_at"])
    return user


def get_or_create_user_from_oauth_profile(*, provider: str, profile: dict) -> HiveUser:
    provider_user_id = profile["provider_user_id"]
    email = profile["email"]
    provider_email = profile.get("provider_email")

    try:
        with transaction.atomic():
            oauth_account = (
                OAuthAccount.objects.select_related("user")
                .select_for_update()
                .filter(provider=provider, provider_user_id=provider_user_id)
                .first()
            )
            if oauth_account:
                if oauth_account.user.status != UserStatus.ACTIVE:
                    raise OAuthError(inactive_account_message())
                oauth_account.provider_email = provider_email
                oauth_account.last_login_at = timezone.now()
                oauth_account.save(update_fields=["provider_email", "last_login_at"])
                _sync_profile_image_from_oauth_profile(
                    user=oauth_account.user,
                    profile=profile,
                )
                return oauth_account.user

            user = (
                HiveUser.objects.select_for_update().filter(email__iexact=email).first()
            )
            if user is not None and user.status != UserStatus.ACTIVE:
                raise OAuthError(inactive_account_message())
            if user is not None:
                raise OAuthError(
                    "같은 이메일의 기존 계정을 확인했습니다. 계정 연결 확인을 다시 진행해 주세요."
                )
            if user is None:
                user = HiveUser.objects.create(
                    username=_build_unique_username(
                        profile.get("username_hint", email.split("@")[0])
                    ),
                    email=email,
                    password_hash=None,
                    status=UserStatus.ACTIVE,
                    profile_image=(profile.get("profile_image") or "").strip() or None,
                )

            OAuthAccount.objects.create(
                user=user,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
                last_login_at=timezone.now(),
            )
            return user
    except IntegrityError as exc:
        raise OAuthError(
            "OAuth 계정 연결을 완료하지 못했습니다. 다시 시도해 주세요."
        ) from exc


def link_oauth_account_to_user(
    *, user: HiveUser, provider: str, profile: dict
) -> OAuthAccount:
    try:
        with transaction.atomic():
            locked_user = HiveUser.objects.select_for_update().get(pk=user.pk)
            if locked_user.status != UserStatus.ACTIVE:
                raise OAuthError(inactive_account_message())

            email = profile["email"].strip().lower()
            provider_user_id = profile["provider_user_id"]
            provider_email = profile.get("provider_email")

            if locked_user.email.strip().lower() != email:
                raise OAuthError(
                    "현재 계정 이메일과 같은 OAuth 계정만 연동할 수 있습니다."
                )

            existing_account = (
                OAuthAccount.objects.select_related("user")
                .select_for_update()
                .filter(provider=provider, provider_user_id=provider_user_id)
                .first()
            )
            if existing_account and existing_account.user_id != locked_user.id:
                raise OAuthError("이미 다른 계정에 연결된 OAuth 계정입니다.")
            if existing_account and existing_account.user_id == locked_user.id:
                existing_account.provider_email = provider_email
                existing_account.last_login_at = timezone.now()
                existing_account.save(update_fields=["provider_email", "last_login_at"])
                _sync_profile_image_from_oauth_profile(
                    user=locked_user,
                    profile=profile,
                )
                return existing_account

            existing_provider_link = locked_user.oauth_accounts.filter(
                provider=provider
            ).first()
            if existing_provider_link:
                raise OAuthError("이미 같은 provider가 현재 계정에 연결되어 있습니다.")

            oauth_account = OAuthAccount.objects.create(
                user=locked_user,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
                last_login_at=timezone.now(),
            )
            _sync_profile_image_from_oauth_profile(
                user=locked_user,
                profile=profile,
            )
            return oauth_account
    except IntegrityError as exc:
        raise OAuthError(
            "OAuth 계정 연결을 완료하지 못했습니다. 다시 시도해 주세요."
        ) from exc
