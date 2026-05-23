# Observability

이 애플리케이션은 `GET /metrics/`에서 Prometheus 형식 메트릭을 노출합니다.

기본 메트릭:

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

## 경우별 구성

### 1. 단일 인스턴스 또는 단일 컨테이너

애플리케이션 주소를 직접 scrape 하면 됩니다.

예시:

```yaml
scrape_configs:
  - job_name: hivewiki-web
    metrics_path: /metrics/
    scrape_interval: 15s
    scrape_timeout: 5s
    static_configs:
      - targets:
          - app.example.com
    scheme: https
```

이 경우 Prometheus는 한 target만 scrape 합니다.

### 2. Kubernetes에서 여러 Pod를 띄우는 경우

Prometheus가 각 Pod를 개별 target으로 scrape 해야 합니다. 외부 Load Balancer나 Ingress 주소 하나만 scrape 하면 Pod별 상태와 집계가 정확하지 않을 수 있습니다.

이 애플리케이션은 `/metrics/`, `/livez/`, `/readyz/`를 HTTPS redirect 예외로 처리합니다. 대신 내부 Service DNS나 scrape host를 사용할 경우 해당 host가 `DJANGO_ALLOWED_HOSTS`에 포함되어 있어야 합니다.

권장 방식:

1. 앱 Pod를 선택하는 `Service`를 만든다.
2. Prometheus에서 `kubernetes_sd_configs`를 사용해 해당 Service의 endpoints를 발견한다.
3. Grafana/PromQL에서는 `sum`, `max`, `min`으로 Pod 결과를 집계한다.

Service 예시:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: hivewiki-web-metrics
  namespace: hivewiki
  labels:
    app: hivewiki-web
spec:
  selector:
    app: hivewiki-web
  ports:
    - name: http
      port: 8000
      targetPort: 8000
```

Prometheus `scrape_configs` 예시:

```yaml
scrape_configs:
  - job_name: hivewiki-web
    metrics_path: /metrics/
    scrape_interval: 15s
    scrape_timeout: 5s

    kubernetes_sd_configs:
      - role: endpoints

    relabel_configs:
      - source_labels: [__meta_kubernetes_namespace]
        regex: hivewiki
        action: keep

      - source_labels: [__meta_kubernetes_service_name]
        regex: hivewiki-web-metrics
        action: keep

      - source_labels: [__meta_kubernetes_endpoint_port_name]
        regex: http
        action: keep

      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod

      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace

      - source_labels: [__meta_kubernetes_service_name]
        target_label: service
```

정상 동작 확인:

- Prometheus UI의 `Status > Targets`에서 Pod 수만큼 target이 보여야 합니다.
- target이 하나만 보이면 외부 LB/Ingress 하나만 scrape하고 있을 가능성이 큽니다.

### 3. 한 Pod 안에 worker 프로세스가 여러 개인 경우

예를 들어 Gunicorn worker 여러 개를 쓰면, Pod 내부 프로세스별 메트릭을 multiprocess 모드로 합쳐야 합니다.

이 애플리케이션은 `PROMETHEUS_MULTIPROC_DIR`가 설정되면 multiprocess registry를 사용합니다.

운영 원칙:

1. Pod 안에서 worker들이 공용으로 쓰는 writable 디렉터리를 준비한다.
2. `PROMETHEUS_MULTIPROC_DIR`를 그 경로로 설정한다.
3. Pod 시작 시 이전 실행의 multiprocess 파일을 정리한다.

주의:

- 이 설정은 "Pod 내부 프로세스 합산"용입니다.
- "여러 Pod 간 합산"은 Prometheus가 각 Pod를 scrape한 뒤 쿼리에서 집계합니다.

## 집계 쿼리 예시

### 전체 요청량

```promql
sum(rate(hivewiki_http_requests_total{job="hivewiki-web"}[5m]))
```

### 전체 5xx 응답량

```promql
sum(rate(hivewiki_http_responses_total{job="hivewiki-web",status_code=~"5.."}[5m]))
```

### 전체 latency p95

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(hivewiki_http_request_duration_seconds_bucket{job="hivewiki-web"}[5m])
  )
)
```

### Pod별 요청량

```promql
sum by (pod) (rate(hivewiki_http_requests_total{job="hivewiki-web"}[5m]))
```

### 모든 Pod가 ready인지 확인

```promql
min(hivewiki_ready{job="hivewiki-web"})
```

### Pod 중 하나라도 살아있는지 확인

```promql
max(hivewiki_up{job="hivewiki-web"})
```

## Grafana

대시보드 템플릿은 `grafana-dashboard-hivewiki-overview.json`을 import 해서 사용할 수 있습니다.

포함 내용:

- 앱 up / ready 상태
- 전체 요청량
- 전체 5xx 비율
- 전체 latency p95
- route별 요청량
- route별 latency p95
- 상태 코드 분포
- dependency readiness

## 파일 목록

- `prometheus-scrape.example.yml`: 단일 인스턴스 scrape 예시
- `grafana-dashboard-hivewiki-overview.json`: Grafana import 템플릿
- `k8s-service.metrics.example.yml`: Kubernetes Pod별 scrape용 Service 예시
- `prometheus-kubernetes-scrape.example.yml`: plain Prometheus의 Kubernetes service discovery 예시

## 배포 레포에 옮길 최소 조합

Kubernetes에서 Pod별 scrape를 하려면 보통 아래 두 파일을 배포 레포로 옮기면 됩니다.

1. `k8s-service.metrics.example.yml`
2. `prometheus-kubernetes-scrape.example.yml`

적용 순서:

1. 앱 Pod를 선택하는 metrics 전용 `Service`를 배포한다.
2. Prometheus `scrape_configs`에 `hivewiki-web` job을 추가한다.
3. Prometheus UI `Status > Targets`에서 Pod 수만큼 target이 잡히는지 확인한다.
4. Grafana에서 `grafana-dashboard-hivewiki-overview.json`을 import 한다.
