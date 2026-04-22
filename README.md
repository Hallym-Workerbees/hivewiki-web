# HiveWiki Web

HiveWiki Web은 HiveWiki 프로젝트의 웹 애플리케이션입니다.  
**Django** 기반으로 개발되며 **HTMX**, **Alpine.js**, **TailwindCSS**를 활용한 서버 렌더링 중심 구조를 목표로 합니다.

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
    urls.py                # 루트 URL 라우팅
  static/
    css/app.css            # 공용 스타일
    js/app.js              # 최소 클라이언트 스크립트
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

로컬 PostgreSQL과 Valkey가 실행 중이라면 아래 명령으로 기본 검증과 서버 실행이 가능합니다.

```bash
UV_CACHE_DIR=/tmp/hivewiki-uv-cache uv run python manage.py migrate
UV_CACHE_DIR=/tmp/hivewiki-uv-cache uv run python manage.py test
UV_CACHE_DIR=/tmp/hivewiki-uv-cache uv run python manage.py runserver
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
- `DJANGO_SECURE_PROXY_SSL_HEADER`: 프록시 뒤에서 HTTPS 판별에 사용할 헤더
  예: `HTTP_X_FORWARDED_PROTO,https`
- `SESSION_COOKIE_AGE`: 세션 유지 시간. 초 단위

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

### 데이터베이스 / 캐시

- `POSTGRES_DB`: PostgreSQL 데이터베이스 이름
- `POSTGRES_USER`: PostgreSQL 사용자
- `POSTGRES_PASSWORD`: PostgreSQL 비밀번호
- `POSTGRES_HOST`: PostgreSQL 호스트
- `POSTGRES_PORT`: PostgreSQL 포트
- `REDIS_URL`: Valkey/Redis URL. 세션 및 캐시에 사용

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
