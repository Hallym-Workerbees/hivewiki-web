# Architecture

## Design Goals

HiveWiki Web의 구조는 아래 세 가지를 우선합니다.

1. 서버 렌더링 중심의 단순한 사용자 경험
2. 운영 가능한 Django 애플리케이션
3. 팀이 계속 확장할 수 있는 명확한 책임 분리

## Why Django + htmx

이 프로젝트는 SPA를 기본값으로 두지 않습니다.

- 서버가 HTML을 직접 렌더링합니다.
- 브라우저는 전체 새로고침 없이 필요한 조각만 htmx로 갱신합니다.
- 복잡한 클라이언트 상태 관리 계층을 추가하지 않아도 됩니다.

이 선택은 특히 아래 상황에 잘 맞습니다.

- 인증/권한 흐름이 많은 앱
- 템플릿 기반 관리자 도구가 중요한 앱
- 검색, 폼, 리스트 갱신이 많은 앱
- 프론트엔드와 백엔드 복잡도를 함께 낮추고 싶은 팀

## Application Layout

### `apps/accounts`

- 로그인, 회원가입, 로그아웃
- OAuth 시작 / 콜백 / 계정 연동
- 마이페이지
- 알림
- 비밀번호 변경
- 프로필 이미지 업로드 준비

핵심 로직은 `services.py`에 모아두고 view는 흐름 제어에 집중합니다.

### `apps/core`

- 공개 메인
- 대시보드
- 관리자 콘솔
- 위키
- 커뮤니티
- 통합 검색

사용자 기능과 운영 기능이 함께 있지만, URL과 템플릿 레벨에서는 비교적 명확히 분리되어 있습니다.

### `config`

- 전역 설정
- URL 라우팅
- health check / metrics
- request logging

운영 성격의 코드를 `config` 아래에 모아둔 덕분에, 비즈니스 기능과 observability 변경을 분리해서 볼 수 있습니다.

## Request Lifecycle

1. 요청이 들어오면 `RequestLoggingMiddleware`가 request context를 엽니다.
2. `request_id`를 생성하고 사용자 ID, 경로, IP를 컨텍스트에 기록합니다.
3. view가 HTML 응답을 생성합니다.
4. 응답 시 요청 수, 상태 코드, latency 메트릭을 기록합니다.
5. JSON 구조화 로그를 stdout으로 남깁니다.

관찰 포인트:

- `/livez/`, `/readyz/`, `/metrics/`는 일반 기능 경로와 다르게 취급됩니다.
- 이 경로들은 로그 억제, HTTPS redirect 예외, host validation 예외를 가질 수 있습니다.

## State and Data

### PostgreSQL

- 비즈니스 데이터의 단일 진실 원천
- 사용자, 콘텐츠, 관계, 운영 상태의 기준 저장소

### Valkey / Redis

- 세션 저장
- 캐시
- 로그인 rate limit 상태

중요한 점:

- 캐시는 없어질 수 있습니다.
- 세션은 초기화될 수 있습니다.
- 따라서 둘 다 durable business storage로 취급하지 않습니다.

## Rendering Strategy

### Full page

- 브라우저 직접 접근 시 전체 템플릿 렌더링
- 레이아웃, 네비게이션, 페이지 컨텍스트를 모두 포함

### Partial HTML

- htmx 요청 시 필요한 fragment만 렌더링
- 반복 조회, 탭 전환, 리스트 갱신, 버튼 토글에 적합

이 방식 덕분에 frontend 복잡도를 크게 늘리지 않고도 상호작용성을 확보합니다.

## Operational Design

### Liveness

- 프로세스가 살아 있는지 빠르게 확인
- 애플리케이션 내부 의존성은 보지 않음

### Readiness

- DB 연결 가능 여부 확인
- 캐시 쓰기/읽기 가능 여부 확인
- 실패 시 `503` 반환

### Metrics

- 요청 수
- 응답 상태
- latency histogram
- readiness 상태
- 프로세스/빌드 정보

메트릭 label은 raw path가 아니라 가능한 경우 Django route pattern을 사용해 cardinality를 낮춥니다.

## Frontend Boundary

브라우저 쪽 JavaScript는 최소화되어 있지만 완전히 없는 것은 아닙니다.

현재 JS는 주로 아래 역할을 맡습니다.

- timezone 동기화 및 시간 표시 보정
- htmx 후처리
- 코드 복사 버튼
- 관리자 새로고침 애니메이션
- 프로필 이미지 업로드 보조

즉 "JS를 피한다"가 아니라 "JS를 필수 상호작용의 얇은 보조층으로 제한한다"에 가깝습니다.

## What This Repo Optimizes For

- 빠른 기능 추가보다 일관된 구조
- 과한 프론트엔드 복잡도 회피
- 운영 관찰 가능성 확보
- 실서비스에 가까운 계정/세션/보안 흐름

## Natural Next Steps

확장 아이디어:

- readiness를 외부 의존성별로 더 세분화
- 주요 사용자 플로우 synthetic check 추가
- 관리자 수집 상태와 운영 메트릭의 연결 강화
- 알림, 검색, 업로드 등 기능별 SLI/SLO 정의

자세한 운영 확장 아이디어는 [observability/healthcheck-ideas.md](./observability/healthcheck-ideas.md)에 정리했습니다.
