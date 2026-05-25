# HiveWiki Web

HiveWiki Web은 HiveWiki 프로젝트의 Django 기반 웹 애플리케이션입니다.  
서버 렌더링을 기본으로 하고, 필요한 상호작용만 `htmx`와 최소한의 JavaScript로 보강합니다.

포트폴리오 관점에서는 "SPA를 만들지 않고도 충분히 빠르고 운영 가능한 웹 앱을 설계한 사례"에 가깝고, 개발자 관점에서는 "Django 템플릿 중심 구조를 팀 단위로 유지보수하기 위한 기준"을 담고 있습니다.

## Highlights

- Django + htmx + Tailwind CSS 기반 서버 렌더링 아키텍처
- PostgreSQL을 source of truth로 사용하는 명확한 상태 관리
- Valkey(Redis-compatible)를 세션, 캐시, rate limit 저장소로 사용
- `GET /livez/`, `GET /readyz/`, `GET /metrics/` 운영 엔드포인트 내장
- Prometheus / Grafana 연동 예시와 구조화 JSON 요청 로그 제공
- 로그인 rate limit, OAuth 로그인/연동, S3 프로필 이미지 업로드 지원
- 브라우저 timezone을 세션에 동기화해 사용자 기준 시각을 안정적으로 렌더링
- 관리자 콘솔, 위키, 커뮤니티, 통합 검색까지 한 저장소에서 제공

## Tech Stack

- Python 3.12
- Django 5
- htmx
- Tailwind CSS
- PostgreSQL
- Valkey / Redis
- uv
- pre-commit
- Ruff
- djLint
- Prometheus client

## Product Surface

- 공개 랜딩 페이지
- 로그인, 회원가입, OAuth 로그인/계정 연동
- 대시보드와 마이페이지
- 위키 탐색, 상세 페이지, 북마크
- 커뮤니티 글/댓글, 좋아요, 북마크
- 통합 검색
- 관리자 콘솔 사용자/태그/수집/콘텐츠 관리

## Architecture At A Glance

### 서버 렌더링 우선

- 전체 페이지 요청은 전체 템플릿을 반환합니다.
- htmx 요청은 필요한 partial HTML만 반환합니다.
- JSON API를 별도로 늘리지 않고 Django view + template 조합으로 기능을 완결합니다.

### 얇은 View, 명시적인 책임 분리

- 입력 검증은 Django form이 담당합니다.
- 인증, 업로드, rate limit 같은 로직은 `apps/accounts/services.py`에 둡니다.
- 운영 기능은 `config/observability.py`, `config/logging.py`, `config/healthchecks.py`에 모읍니다.

### 상태 관리 원칙

- PostgreSQL이 비즈니스 데이터의 단일 진실 원천입니다.
- Valkey는 세션, 캐시, 일시적 상태에만 사용합니다.
- 프로세스 메모리를 공유 상태로 간주하지 않습니다.

## Repository Map

```txt
hivewiki-web/
  apps/
    accounts/      # 인증, 프로필, OAuth, 알림, 비밀번호 변경
    core/          # 대시보드, 위키, 커뮤니티, 검색, 관리자 콘솔
  config/
    settings.py    # 환경설정, 보안, 세션, 캐시, 로깅
    urls.py        # 루트 URL과 운영 엔드포인트
    observability.py
    logging.py
    healthchecks.py
  templates/       # 레이아웃, 페이지, partial 템플릿
  static/          # 최소 JS와 공용 스타일
  docs/
    architecture.md
    development.md
    observability/
```

## Quick Start

### 1. 로컬 준비

```bash
git clone <repository-url>
cd hivewiki-web
cp .env.example .env
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

Nix devshell을 쓰는 팀원이라면 아래 방식이 기준입니다.

```bash
nix develop
```

이 devshell은 `.venv` 생성, `uv sync`, pre-commit hook 설치까지 처리합니다.

### 2. 필수 인프라 실행

로컬에서 최소한 아래 두 가지가 떠 있어야 합니다.

- PostgreSQL
- Valkey 또는 Redis

`.env.example`의 기본값은 다음 로컬 주소를 기준으로 합니다.

- PostgreSQL: `127.0.0.1:5432`
- Redis: `127.0.0.1:6379/0`

### 3. 마이그레이션, 테스트, 서버 실행

```bash
uv run python manage.py migrate
uv run python manage.py test
uv run python manage.py runserver
```

devshell 기준 예시는 아래와 같습니다.

```bash
nix develop --command python manage.py migrate
nix develop --command python manage.py test
nix develop --command python manage.py runserver
```

## Developer Workflow

일상적인 개발 루틴은 아래 순서를 권장합니다.

1. `.env`를 준비하고 PostgreSQL / Valkey를 띄웁니다.
2. `python manage.py test`로 변경 영역의 기본 동작을 먼저 확인합니다.
3. 화면 변경 시 full-page 응답과 htmx partial 응답을 모두 확인합니다.
4. `pre-commit run --all-files`로 포맷, lint, secret check를 통과시킵니다.
5. 커밋 메시지는 영어 Conventional Commits 형식을 사용합니다.

기여 방식과 리뷰 기준은 [CONTRIBUTING.md](./CONTRIBUTING.md)를 참고하세요.

## Environment Variables

기본 예시는 [.env.example](./.env.example)에 있습니다.  
핵심 설정은 fallback 없이 강제되므로, 누락되면 애플리케이션이 시작되지 않을 수 있습니다.

### 핵심 앱 설정

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_CLIENT_IP_HEADER`

### 데이터 저장소

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_CONNECT_TIMEOUT`
- `REDIS_URL`
- `REDIS_SOCKET_CONNECT_TIMEOUT`
- `REDIS_SOCKET_TIMEOUT`

### 세션 / 보안

- `DJANGO_SESSION_COOKIE_SECURE`
- `DJANGO_SESSION_COOKIE_SAMESITE`
- `DJANGO_CSRF_COOKIE_SECURE`
- `DJANGO_CSRF_COOKIE_SAMESITE`
- `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_SECURE_HSTS_SECONDS`
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`
- `DJANGO_SECURE_HSTS_PRELOAD`
- `DJANGO_SECURE_CONTENT_TYPE_NOSNIFF`
- `DJANGO_X_FRAME_OPTIONS`
- `SESSION_COOKIE_AGE`

### 로깅 / 운영

- `DJANGO_LOG_LEVEL`
- `DJANGO_LOG_JSON`
- `DJANGO_LOG_HEALTHCHECKS`
- `DJANGO_SECURE_PROXY_SSL_HEADER`

### 인증 / 업로드

- `LOGIN_RATE_LIMIT_ATTEMPTS`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GITHUB_OAUTH_CLIENT_ID`
- `GITHUB_OAUTH_CLIENT_SECRET`
- `AWS_S3_UPLOAD_BUCKET`
- `AWS_S3_UPLOAD_REGION`
- `AWS_S3_UPLOAD_ACCESS_KEY_ID`
- `AWS_S3_UPLOAD_SECRET_ACCESS_KEY`
- `AWS_S3_UPLOAD_ENDPOINT_URL`
- `AWS_S3_UPLOAD_PUBLIC_BASE_URL`
- `AWS_S3_PROFILE_IMAGE_PREFIX`

상세 설명은 [docs/development.md](./docs/development.md)에 정리했습니다.

## Things Every Developer Should Know

### 1. htmx 응답 규칙

- 전체 페이지 요청이면 전체 템플릿을 반환합니다.
- htmx 요청이면 partial 템플릿을 반환합니다.
- validation error가 나면 관련 폼 partial을 다시 렌더링합니다.
- htmx 기능을 위해 JSON API를 새로 만들지 않습니다.

### 2. 시간대 처리

- 사용자 브라우저 timezone은 `POST /auth/timezone/`로 세션 키 `django_timezone`에 저장됩니다.
- 로그인/로그아웃에서 `session.flush()`가 일어나더라도 이 timezone은 유지되어야 합니다.
- 시간 민감 UI는 기존 `timezone-sensitive` 패턴을 사용해야 합니다.

### 3. 요청 로깅

- 요청마다 내부 `request_id`를 새로 발급합니다.
- 응답 헤더 `X-Request-ID`에도 같은 값을 반환합니다.
- 프록시가 넘긴 `X-Request-ID`는 `upstream_request_id`로 별도 기록합니다.
- 기본 로그 포맷은 JSON이며 stdout을 대상으로 합니다.

### 4. Health Check와 Metrics는 기능 일부가 아니라 운영 계약입니다

- `/livez/`는 프로세스 생존 확인용입니다.
- `/readyz/`는 DB와 캐시 준비 상태를 확인합니다.
- `/metrics/`는 Prometheus scrape endpoint입니다.
- 이 경로들은 HTTPS redirect와 host validation 예외 처리까지 고려되어 있습니다.

### 5. DB schema 변경은 별도 합의 대상입니다

이 저장소에서는 기능 요청이 있더라도 스키마 변경이 필요하면 먼저 문서와 최종 요약에서 명시하는 편이 안전합니다.

## Observability

현재 내장 운영 엔드포인트:

- `GET /livez/`
- `GET /readyz/`
- `GET /metrics/`

기본 메트릭:

- `hivewiki_up`
- `hivewiki_process_start_time_seconds`
- `hivewiki_build_info`
- `hivewiki_readiness_check{check="database|cache"}`
- `hivewiki_ready`
- `hivewiki_http_requests_total{method,route}`
- `hivewiki_http_responses_total{method,route,status_code}`
- `hivewiki_http_request_duration_seconds_*`

관련 문서:

- [docs/observability/README.md](./docs/observability/README.md)
- [docs/observability/healthcheck-ideas.md](./docs/observability/healthcheck-ideas.md)

## Documentation Index

- [CONTRIBUTING.md](./CONTRIBUTING.md): 브랜치, 리뷰, 테스트, 커밋 규칙
- [docs/development.md](./docs/development.md): 로컬 개발, 환경변수, 디버깅 포인트
- [docs/architecture.md](./docs/architecture.md): 앱 구조와 설계 원칙
- [docs/observability/README.md](./docs/observability/README.md): 메트릭, Prometheus, Grafana
- [docs/observability/healthcheck-ideas.md](./docs/observability/healthcheck-ideas.md): 현재 구현을 확장할 수 있는 운영 아이디어

## Portfolio Framing

이 프로젝트는 아래 관점에서 설명하기 좋습니다.

- Django를 단순 CRUD 프레임워크가 아니라 운영 가능한 웹 애플리케이션 플랫폼으로 사용한 사례
- 서버 렌더링과 htmx를 조합해 복잡도를 낮추면서도 상호작용성을 확보한 사례
- request ID, health checks, readiness, metrics, JSON logging까지 포함한 운영 관점의 설계 사례
- 사용자 timezone, OAuth, rate limit, presigned upload 같은 현실적인 웹 요구사항을 통합한 사례

## Quality Gates

- `uv-lock`
- Ruff lint / format
- djLint
- gitleaks
- Commitizen

가능하면 최종 변경 전 아래 명령을 실행합니다.

```bash
pre-commit run --all-files
```

## Deployment Notes

- 이 저장소는 애플리케이션 코드 저장소입니다.
- 인프라, GitOps, Prometheus 배포 설정은 별도 저장소에서 관리됩니다.
- 운영 변경이 세션, 캐시, 환경변수, static asset, startup behavior에 영향을 주면 후속 작업을 배포 저장소에도 반영해야 합니다.
