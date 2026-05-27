import ipaddress

from django.conf import settings

from config.observability import liveness_probe, metrics_view, readiness_probe

HEALTHCHECK_PATHS = frozenset(("/livez/", "/readyz/"))
ELB_HEALTHCHECK_USER_AGENT_PREFIX = "ELB-HealthChecker/"
HEALTHCHECK_VIEWS = {
    "/livez/": liveness_probe,
    "/readyz/": readiness_probe,
    "/metrics/": metrics_view,
}


class HealthcheckHostNormalizationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._normalize_host_for_healthcheck(request)
        healthcheck_view = HEALTHCHECK_VIEWS.get(request.path)
        if healthcheck_view is not None:
            return healthcheck_view(request)
        return self.get_response(request)

    def _normalize_host_for_healthcheck(self, request):
        if request.path not in HEALTHCHECK_PATHS:
            return

        user_agent = request.META.get("HTTP_USER_AGENT", "")
        if not user_agent.startswith(ELB_HEALTHCHECK_USER_AGENT_PREFIX):
            return

        host = request.META.get("HTTP_HOST", "")
        if not _is_ip_host(host):
            return

        normalized_host = _first_canonical_allowed_host()
        if normalized_host is None:
            return

        request.META["HTTP_HOST"] = normalized_host


def _is_ip_host(host):
    if not host:
        return False

    candidate = host
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    elif ":" in candidate and candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]

    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return False

    return True


def _first_canonical_allowed_host():
    for host in settings.ALLOWED_HOSTS:
        normalized_host = host.lstrip(".").strip()
        if not normalized_host or normalized_host == "*":
            continue
        if _is_ip_host(normalized_host):
            continue
        return normalized_host
    return None
