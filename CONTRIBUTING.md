# Contributing

이 문서는 HiveWiki Web에 기여하는 개발자를 위한 실무 가이드입니다.  
목표는 "작동하는 코드"보다 "팀이 계속 유지보수할 수 있는 코드"를 남기는 것입니다.

## Working Principles

- 가장 작은 변경으로 문제를 해결합니다.
- 관련 없는 리팩터링은 섞지 않습니다.
- Django 템플릿 서버 렌더링 패턴을 유지합니다.
- htmx를 쓰는 기능은 HTML 응답을 기본으로 합니다.
- 비즈니스 로직은 template가 아니라 form, service, model method에 둡니다.
- 캐시와 세션은 영속 스토리지로 취급하지 않습니다.

## Before You Start

1. `.env.example`을 복사해 `.env`를 준비합니다.
2. PostgreSQL과 Valkey/Redis를 띄웁니다.
3. `uv sync` 또는 `nix develop`로 개발 환경을 맞춥니다.
4. `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg`를 실행합니다.

## Branch and Commit Expectations

- 브랜치 전략은 팀 정책을 따르되, 한 브랜치에는 하나의 목적만 담는 편이 좋습니다.
- 커밋 메시지는 영어로 작성합니다.
- Conventional Commits 형식을 사용합니다.

예시:

- `feat: add profile image upload preparation endpoint`
- `fix: preserve timezone across logout flow`
- `docs: rewrite developer onboarding guide`

## Change Design Checklist

코드를 쓰기 전에 아래를 확인하는 편이 좋습니다.

- 이 변경이 전체 페이지 요청과 htmx 요청을 모두 고려하는가
- validation 실패 시 partial 재렌더링이 가능한가
- request log와 운영 메트릭이 관측 가능한가
- 세션 flush가 일어나는 흐름에서 `django_timezone` 보존이 필요한가
- 스키마 변경이 필요한가

스키마 변경이 필요하면 바로 구현하기보다 먼저 변경 필요성을 명시하고 합의하는 편이 안전합니다.

## Testing Expectations

최소 기준:

1. 변경한 기능에 직접 관련된 테스트를 실행합니다.
2. 요청 형태가 두 가지면 둘 다 확인합니다.
3. 에러 응답과 권한 경계도 확인합니다.

자주 쓰는 명령:

```bash
uv run python manage.py test
uv run python manage.py test apps.accounts
uv run python manage.py test apps.core
uv run python manage.py test config
```

Nix devshell을 사용하는 경우:

```bash
nix develop --command python manage.py test
```

## Code Style

### Django

- view는 얇게 유지합니다.
- 입력 검증은 Django form을 우선 사용합니다.
- 복잡한 로직은 service 함수 또는 model method로 이동합니다.
- 새 기능이 htmx 전용이라면 JSON보다 HTML partial 응답을 우선합니다.

### Templates

- 템플릿에는 비즈니스 로직을 넣지 않습니다.
- 기존 partial 구조를 재사용합니다.
- Tailwind class list는 읽을 수 있게 유지합니다.
- 시간 표시가 timezone 민감하면 기존 `timezone-sensitive` 패턴을 사용합니다.

### Logging and Operations

- `print()`로 디버깅하지 않습니다.
- 애플리케이션 로그는 `logging.getLogger(__name__)`를 사용합니다.
- JSON 로그 포맷과 request context 필드를 깨지 않게 유지합니다.
- `request_id`, `method`, `path`, `status_code`, `duration_ms`, `user_id`, `remote_addr`는 보존 대상입니다.

## Review Checklist

리뷰어는 아래 항목을 먼저 봅니다.

- 동작 회귀 가능성
- 권한 및 인증 경계
- 상태 저장 위치가 적절한지
- htmx와 full-page 응답 분리가 맞는지
- 운영 엔드포인트나 로그/메트릭에 부작용이 없는지
- 문서화가 필요한 변경인데 빠져 있지 않은지

## Documentation Expectations

아래 경우에는 문서도 같이 갱신해야 합니다.

- 새 환경변수를 추가한 경우
- 운영 엔드포인트 또는 메트릭이 바뀐 경우
- 로컬 개발 흐름이 바뀐 경우
- 보안/세션/캐시 동작이 바뀐 경우
- 포트폴리오 설명 관점에서 중요한 기능이 추가된 경우

문서 위치:

- `README.md`
- `docs/development.md`
- `docs/architecture.md`
- `docs/observability/`

## Final Checks

가능하면 최종 커밋 전에 아래를 실행합니다.

```bash
pre-commit run --all-files
```

pre-commit에는 아래 검사가 포함됩니다.

- `uv-lock`
- Ruff
- djLint
- gitleaks
- Commitizen
