# Development Guide

## Local Environment

기본 개발 환경:

- Python 3.12
- PostgreSQL
- Valkey 또는 Redis
- uv

선택 환경:

- Nix devshell

## First Run

```bash
cp .env.example .env
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run python manage.py migrate
uv run python manage.py runserver
```

Nix를 쓴다면:

```bash
nix develop
```

## Environment Variables

### 필수에 가까운 값

- `DJANGO_SECRET_KEY`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `REDIS_URL`

### 개발 중 자주 보는 값

- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_LOG_LEVEL`
- `DJANGO_LOG_JSON`
- `DJANGO_LOG_HEALTHCHECKS`
- `LOGIN_RATE_LIMIT_ATTEMPTS`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`

### 보안 / 프록시

- `DJANGO_SESSION_COOKIE_SECURE`
- `DJANGO_CSRF_COOKIE_SECURE`
- `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_SECURE_PROXY_SSL_HEADER`
- `DJANGO_X_FRAME_OPTIONS`

### OAuth

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GITHUB_OAUTH_CLIENT_ID`
- `GITHUB_OAUTH_CLIENT_SECRET`

### S3 업로드

- `AWS_S3_UPLOAD_BUCKET`
- `AWS_S3_UPLOAD_REGION`
- `AWS_S3_UPLOAD_ACCESS_KEY_ID`
- `AWS_S3_UPLOAD_SECRET_ACCESS_KEY`
- `AWS_S3_UPLOAD_ENDPOINT_URL`
- `AWS_S3_UPLOAD_PUBLIC_BASE_URL`
- `AWS_S3_PROFILE_IMAGE_PREFIX`

프로필 이미지 업로드가 실제로 동작하려면 최소한 아래 값이 있어야 합니다.

- `AWS_S3_UPLOAD_BUCKET`
- `AWS_S3_UPLOAD_REGION`
- `AWS_S3_UPLOAD_PUBLIC_BASE_URL`

## Development Commands

```bash
uv run python manage.py migrate
uv run python manage.py test
uv run python manage.py test apps.accounts
uv run python manage.py test apps.core
uv run python manage.py test config
uv run python manage.py runserver
pre-commit run --all-files
```

## Timezone Handling

- 브라우저 timezone은 `POST /auth/timezone/`를 통해 세션에 저장됩니다.
- 세션 키 이름은 `django_timezone`입니다.
- 로그인/로그아웃에서 세션 재생성이 일어나더라도 timezone은 유지되어야 합니다.
- 시간 표시 UI는 기존 `timezone-sensitive` 패턴을 따릅니다.

이 부분은 "처음 서버가 렌더링한 시간"과 "브라우저 기준 최종 표시 시간"이 다를 수 있기 때문에, 템플릿을 새로 만들 때 가장 자주 놓치는 영역 중 하나입니다.

## Logging

애플리케이션은 stdout에 JSON 구조화 로그를 남깁니다.

주요 필드:

- `timestamp`
- `level`
- `logger`
- `message`
- `request_id`
- `upstream_request_id`
- `method`
- `path`
- `status_code`
- `duration_ms`
- `user_id`
- `remote_addr`

헬스체크 접근 로그는 기본적으로 숨겨져 있으며, 필요하면 `DJANGO_LOG_HEALTHCHECKS=True`로 켤 수 있습니다.

## Health Endpoints

- `GET /livez/`: 프로세스 생존 확인
- `GET /readyz/`: DB/캐시 readiness 확인
- `GET /metrics/`: Prometheus endpoint

이 경로들은 일반 사용자 기능이 아니라 운영 계약의 일부이므로, 동작을 바꾸면 문서와 모니터링 설정도 함께 검토해야 합니다.

## Where To Change Things

### 인증 / 계정 / 업로드

- `apps/accounts/forms.py`
- `apps/accounts/services.py`
- `apps/accounts/views.py`

### 위키 / 커뮤니티 / 관리자 콘솔 / 검색

- `apps/core/views.py`
- `apps/core/urls.py`
- 관련 `templates/pages/` 및 `templates/partials/`

### 운영 / 로깅 / 헬스체크

- `config/observability.py`
- `config/logging.py`
- `config/healthchecks.py`
- `config/settings.py`

## Common Pitfalls

- htmx 요청인데 전체 페이지를 반환하는 실수
- validation error에서 partial을 다시 렌더링하지 않는 실수
- 캐시나 세션을 영속 비즈니스 상태처럼 사용하는 실수
- `session.flush()` 이후 timezone이 사라지는 회귀
- metrics route에 high-cardinality label을 추가하는 실수
- observability 경로에 대한 로그/redirect/host validation 예외를 깨는 실수
