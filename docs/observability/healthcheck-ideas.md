# Healthcheck Strategy Notes

핵심은 "probe와 ALB health check가 애플리케이션 일반 요청 처리에 막히지 않게 우회한다"입니다.

## What This Is Solving

운영 환경에서는 아래 같은 요청이 먼저 안정적으로 통과해야 합니다.

- Kubernetes probe
- AWS ALB / ELB health check
- Prometheus scrape

그런데 일반 애플리케이션 미들웨어 체인을 그대로 타게 두면 아래 문제를 쉽게 만납니다.

- IP Host 기반 health check가 `ALLOWED_HOSTS`에 막힘
- HTTPS redirect에 걸려 probe가 실패함
- 불필요하게 세션, 인증, 페이지 렌더링 체인까지 탐

이 프로젝트에서 한 접근은 "health check 요청을 일반 사용자 요청처럼 취급하지 않는다"입니다.

## Current Strategy

구현 위치:

- [`config/healthchecks.py`](../../config/healthchecks.py)
- [`config/observability.py`](../../config/observability.py)
- [`config/tests/test_healthchecks.py`](../../config/tests/test_healthchecks.py)

현재 전략은 두 가지입니다.

### 1. health check 경로를 미들웨어 초입에서 short-circuit

`HealthcheckHostNormalizationMiddleware`는 `/livez/`, `/readyz/`, `/metrics/` 요청을 보면 일반 downstream view까지 보내지 않고 바로 health check view를 호출합니다.

의도:

- probe 요청을 일반 앱 라우팅/렌더링과 분리
- health check가 앱 기능 코드 변화에 덜 영향받게 유지
- 운영 경로를 가능한 짧고 예측 가능하게 유지

### 2. ALB health check의 IP Host를 canonical host로 정규화

ALB/ELB health check는 `HTTP_HOST`에 도메인 대신 IP가 들어올 수 있습니다.  
이 경우 Django의 host validation에 걸릴 수 있으므로, `/livez/`와 `/readyz/`에 대해서만 ELB user agent를 보고 host를 첫 번째 canonical `ALLOWED_HOSTS` 값으로 치환합니다.

의도:

- 일반 사용자 요청 보안 정책은 유지
- health check 요청만 예외 처리
- "모든 IP host 허용" 같은 넓은 완화책을 피함

## Why `/metrics/` Is Also Short-circuited

`/metrics/`도 같은 미들웨어에서 바로 처리합니다.

이유:

- Prometheus가 Pod IP 기반으로 scrape 할 수 있음
- scrape 요청이 일반 host validation에 막히지 않게 해야 함
- metrics endpoint는 앱 기능 페이지와 별개 운영 경로이기 때문

또한 settings에서 `/livez/`, `/readyz/`, `/metrics/`는 HTTPS redirect 예외로 둡니다.

## What The Endpoints Mean

- `GET /livez/`: 프로세스가 살아 있는지만 확인
- `GET /readyz/`: database, cache 준비 상태 확인
- `GET /metrics/`: Prometheus 메트릭 노출

여기서 중요한 점은 `livez`와 `readyz`의 목적을 섞지 않는 것입니다.

- `livez`는 최대한 가볍게
- `readyz`는 트래픽을 받아도 되는지 판단

## Why This Approach Is Pragmatic

이 방식의 장점:

- 인프라 헬스체크가 앱 상세 구현에 덜 결합됨
- ALB/Kubernetes/Prometheus 같은 외부 시스템 요구사항을 앱 안에서 명시적으로 처리 가능
- 보안 완화 범위를 health check 경로로 국한 가능
