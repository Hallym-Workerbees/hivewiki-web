# HiveWiki Web

HiveWiki Web은 HiveWiki 프로젝트의 웹 애플리케이션입니다.  
**Django** 기반으로 개발되며 **htmx**, **Tailwind CSS**, 그리고 최소한의 커스텀 JavaScript를 활용한 서버 렌더링 중심 구조를 목표로 합니다.

## 개발 환경

이 프로젝트는 다음 도구들을 사용합니다.

- Python 3.12
- Django
- uv (dependency management)
- pre-commit (코드 품질 자동 검사)
- Ruff (Python lint + formatter)
- djLint (Django template lint/format)
- gitleaks (secret detection)
- commitizen (commit message validation)

## 프로젝트 구조

현재 기준의 주요 폴더 구조는 아래와 같습니다.

```txt
hivewiki-web/
  apps/
    accounts/              # 회원가입, 로그인, 로그아웃, 마이페이지, 비밀번호 변경
      forms.py             # 인증/프로필 관련 Django form
      models.py            # HiveUser 모델
      services.py          # 비밀번호 해시, 세션 로그인, rate limit 로직
      tests/               # 인증 플로우 테스트
      urls.py
      views.py
    core/                  # 홈, 대시보드, 커뮤니티/위키 진입 화면
      urls.py
      views.py
  config/
    settings.py            # Django 설정, .env 로딩, 보안/세션/캐시 설정
    urls.py                # 루트 URL 라우팅 및 운영 엔드포인트
    observability.py       # liveness/readiness probe, Prometheus metrics
  static/
    css/app.css            # 공용 스타일
    js/app.js              # 최소 클라이언트 스크립트와 timezone 동기화
  templates/
    layouts/               # public/app/auth 레이아웃
    pages/                 # 페이지 템플릿
    partials/              # 재사용 가능한 컴포넌트 템플릿
  .env.example             # 개발/배포용 환경변수 예시
  manage.py
```

## 시작하기

```bash
git clone <repository-url>
cd hivewiki-web
uv sync
cp .env.example .env
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

이 저장소에서는 `nix develop --command ...` 실행도 지원하며, 로컬 도구 버전을 맞춰야 할 때 권장합니다.

로컬 PostgreSQL과 Valkey가 실행 중이라면 아래 명령으로 기본 검증과 서버 실행이 가능합니다.

```bash
UV_CACHE_DIR=/tmp/hivewiki-uv-cache uv run python manage.py migrate
UV_CACHE_DIR=/tmp/hivewiki-uv-cache uv run python manage.py test
UV_CACHE_DIR=/tmp/hivewiki-uv-cache uv run python manage.py runserver
```

같은 작업을 devshell 안에서 실행하려면 아래처럼 사용할 수 있습니다.

```bash
nix develop --command python manage.py migrate
nix develop --command python manage.py test
nix develop --command python manage.py runserver
```

이 프로젝트는 pre-commit hooks를 사용합니다.  
코드가 자동으로 수정되면 커밋이 중단될 수 있으며, 수정된 파일을 확인한 뒤 다시 add하고 커밋하면 됩니다.

Commit message는 **영어로 작성해야 하며**, Conventional Commits 규칙을 따릅니다.  
자세한 규칙은 이 [문서](https://commitizen-tools.github.io/commitizen/tutorials/writing_commits/)를 참고하세요.

## 환경변수

기본 예시는 [.env.example](./.env.example)에 있습니다. 로컬 개발에서는 `.env`를 사용하고, 배포에서는 인프라 레벨에서 동일한 키를 주입하면 됩니다.

이 프로젝트는 핵심 설정에 대해 fallback을 두지 않습니다.  
즉 `DJANGO_SECRET_KEY`, PostgreSQL 접속 정보, `REDIS_URL` 이 누락되면 앱이 시작되지 않습니다.

### Django 기본 설정

- `DJANGO_SECRET_KEY`: Django secret key. 배포에서는 반드시 강한 랜덤 값 사용
- `DJANGO_DEBUG`: 개발에서는 `True`, 배포에서는 `False`
- `DJANGO_ALLOWED_HOSTS`: 허용할 호스트 목록. 쉼표로 구분
- `DJANGO_CSRF_TRUSTED_ORIGINS`: CSRF trusted origin 목록. 쉼표로 구분
- `DJANGO_CLIENT_IP_HEADER`: 로그인 rate limit에 사용할 신뢰 헤더 이름
  예: `HTTP_X_FORWARDED_FOR`

### 세션 / CSRF / 보안 설정

- `DJANGO_SESSION_COOKIE_SECURE`: HTTPS에서만 세션 쿠키 전송 여부
- `DJANGO_SESSION_COOKIE_SAMESITE`: 세션 쿠키 SameSite 값. 기본 `Lax`
- `DJANGO_CSRF_COOKIE_SECURE`: HTTPS에서만 CSRF 쿠키 전송 여부
- `DJANGO_CSRF_COOKIE_SAMESITE`: CSRF 쿠키 SameSite 값. 기본 `Lax`
- `DJANGO_SECURE_SSL_REDIRECT`: HTTP 요청을 HTTPS로 리다이렉트할지 여부
- `DJANGO_SECURE_HSTS_SECONDS`: HSTS max-age
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`: HSTS 서브도메인 포함 여부
- `DJANGO_SECURE_HSTS_PRELOAD`: HSTS preload 선언 여부
- `DJANGO_SECURE_CONTENT_TYPE_NOSNIFF`: `X-Content-Type-Options: nosniff` 사용 여부
- `DJANGO_X_FRAME_OPTIONS`: `X-Frame-Options` 값. 기본 `DENY`
- `DJANGO_LOG_LEVEL`: 애플리케이션 로그 레벨. 기본 `INFO`
- `DJANGO_LOG_JSON`: JSON 구조화 로그 사용 여부. 기본 `True`
- `DJANGO_LOG_HEALTHCHECKS`: `/livez/`, `/readyz/` access 로그 출력 여부. 기본 `False`
- `DJANGO_SECURE_PROXY_SSL_HEADER`: 프록시 뒤에서 HTTPS 판별에 사용할 헤더
  예: `HTTP_X_FORWARDED_PROTO,https`
- `SESSION_COOKIE_AGE`: 세션 유지 시간. 초 단위

브라우저 timezone은 별도 엔드포인트 `POST /auth/timezone/`를 통해 세션 키 `django_timezone`에 저장됩니다. 이 값은 로그인/로그아웃 과정에서 세션이 재설정되어도 유지되며, 서버는 이를 사용해 사용자별 시간대를 활성화하고 클라이언트는 timezone-sensitive UI를 로컬 시간대로 다시 렌더링합니다.

### 로깅

애플리케이션은 표준 출력으로 JSON 구조화 로그를 남깁니다. 요청 로그에는 최소한 아래 필드가 포함됩니다.

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

애플리케이션은 내부 `request_id`를 항상 새로 생성하고 응답 헤더 `X-Request-ID`에도 같은 값을 돌려줍니다. 앞단 프록시나 Ingress가 `X-Request-ID`를 넘기면 `upstream_request_id`로 별도 기록합니다.

### 로그인 rate limit

- `LOGIN_RATE_LIMIT_ATTEMPTS`: 허용할 로그인 실패 횟수
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`: rate limit 시간 창. 초 단위

현재 구현은 `client_ip + email` 기준으로 실패 횟수를 캐시에 저장합니다.  
앞단 프록시가 실제 클라이언트 IP를 정리해 준다는 전제에서, 앱은 `DJANGO_CLIENT_IP_HEADER` 또는 `REMOTE_ADDR`를 사용합니다.

### OAuth

- `GOOGLE_OAUTH_CLIENT_ID`: Google OAuth client ID
- `GOOGLE_OAUTH_CLIENT_SECRET`: Google OAuth client secret
- `GITHUB_OAUTH_CLIENT_ID`: GitHub OAuth app client ID
- `GITHUB_OAUTH_CLIENT_SECRET`: GitHub OAuth app client secret

OAuth callback URL은 현재 요청의 host/scheme를 기준으로 서버에서 생성합니다.  
배포 환경에서는 프록시/Ingress 설정과 `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DJANGO_SECURE_PROXY_SSL_HEADER`가 올바르게 맞아 있어야 합니다.

### S3 프로필 이미지 업로드

- `AWS_S3_UPLOAD_BUCKET`: 프로필 이미지 업로드 대상 버킷 이름
- `AWS_S3_UPLOAD_REGION`: 업로드 대상 리전
- `AWS_S3_UPLOAD_ACCESS_KEY_ID`: S3 접근 키. IAM role 등을 쓰지 않으면 필요
- `AWS_S3_UPLOAD_SECRET_ACCESS_KEY`: S3 시크릿 키. IAM role 등을 쓰지 않으면 필요
- `AWS_S3_UPLOAD_ENDPOINT_URL`: S3 호환 스토리지용 endpoint URL. AWS S3 기본 endpoint를 쓸 때는 비워둘 수 있음
- `AWS_S3_UPLOAD_PUBLIC_BASE_URL`: 업로드 후 사용자에게 노출할 공개 URL prefix
- `AWS_S3_PROFILE_IMAGE_PREFIX`: object key prefix. 기본값 `profiles`

프로필 이미지 업로드가 활성화되려면 애플리케이션 관점에서 최소한 아래 값이 필요합니다.

- `AWS_S3_UPLOAD_BUCKET`
- `AWS_S3_UPLOAD_REGION`
- `AWS_S3_UPLOAD_PUBLIC_BASE_URL`

`AWS_S3_UPLOAD_PUBLIC_BASE_URL`은 명시적으로 넣는 것을 권장합니다. 이 값은 presigned POST 업로드 대상이 아니라 업로드 완료 후 저장할 공개 URL의 prefix로 사용됩니다. 따라서 다음과 같은 값이 가능합니다.

- AWS S3 기본 공개 URL: `https://my-bucket.s3.ap-northeast-2.amazonaws.com`
- CloudFront 기본 도메인: `https://d123exampleabcd.cloudfront.net`
- CloudFront 커스텀 도메인: `https://media.example.com`

예를 들어 `AWS_S3_UPLOAD_PUBLIC_BASE_URL=https://media.example.com` 이고 `AWS_S3_PROFILE_IMAGE_PREFIX=profiles` 라면 최종 이미지 URL은 `https://media.example.com/profiles/<user-id>/<random>.png` 형태가 됩니다.

`AWS_S3_UPLOAD_ENDPOINT_URL`은 자동 생성되지 않습니다. AWS S3를 그대로 쓰는 경우에는 비워둘 수 있고, MinIO/R2/Object Storage 같은 S3 호환 스토리지를 쓸 때만 직접 지정하면 됩니다.

반대로 `AWS_S3_UPLOAD_PUBLIC_BASE_URL`은 비어 있을 경우 아래 규칙으로 자동 유도될 수 있습니다.

- `AWS_S3_UPLOAD_ENDPOINT_URL`이 있으면 `https://<endpoint>/<bucket>` 형태
- 아니면 `https://<bucket>.s3.<region>.amazonaws.com` 형태

다만 CloudFront를 쓰는 배포 환경에서는 자동 유도값 대신 실제 공개 도메인을 명시하는 편이 안전합니다.

### 데이터베이스 / 캐시

- `POSTGRES_DB`: PostgreSQL 데이터베이스 이름
- `POSTGRES_USER`: PostgreSQL 사용자
- `POSTGRES_PASSWORD`: PostgreSQL 비밀번호
- `POSTGRES_HOST`: PostgreSQL 호스트
- `POSTGRES_PORT`: PostgreSQL 포트
- `REDIS_URL`: Valkey/Redis URL. 세션 및 캐시에 사용

## 운영 엔드포인트

- `GET /livez/`: 프로세스 liveness 확인. 정상 시 `200 OK`
- `GET /readyz/`: PostgreSQL과 Valkey readiness 확인. 하나라도 실패하면 `503 Service Unavailable`
- `GET /metrics/`: Prometheus scrape endpoint

`/metrics/`는 최소한 아래 메트릭을 제공합니다.

- `hivewiki_up`
- `hivewiki_process_start_time_seconds`
- `hivewiki_build_info`
- `hivewiki_readiness_check{check="database|cache"}`
- `hivewiki_ready`
- `hivewiki_http_requests_total{method,route}`
- `hivewiki_http_responses_total{method,route,status_code}`
- `hivewiki_http_request_duration_seconds_bucket{method,route,le}`
- `hivewiki_http_request_duration_seconds_sum{method,route}`
- `hivewiki_http_request_duration_seconds_count{method,route}`

HTTP 메트릭의 `route` 라벨은 가능한 경우 raw path 대신 Django route pattern 기준으로 집계해 path parameter로 인한 cardinality 증가를 줄입니다.

## 배포 시 권장값

배포 환경에서는 최소한 아래 값들을 권장합니다.

```env
DJANGO_DEBUG=False
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
DJANGO_SECURE_HSTS_PRELOAD=True
```
