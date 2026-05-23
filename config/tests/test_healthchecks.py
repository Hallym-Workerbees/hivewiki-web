from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import path

from config.healthchecks import HealthcheckHostNormalizationMiddleware
from config.observability import metrics_view


def ok_view(_request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("livez/", ok_view),
    path("metrics/", metrics_view),
    path("dashboard/", ok_view),
]


@override_settings(
    ROOT_URLCONF="config.tests.test_healthchecks",
    ALLOWED_HOSTS=["test.hive-wiki.com"],
)
class HealthcheckHostNormalizationMiddlewareTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_elb_healthcheck_ip_host_is_normalized_for_livez(self):
        response = self.client.get(
            "/livez/",
            HTTP_HOST="10.0.0.42",
            HTTP_USER_AGENT="ELB-HealthChecker/2.0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "ok\n")

    def test_non_healthcheck_path_still_rejects_ip_host(self):
        response = self.client.get(
            "/dashboard/",
            HTTP_HOST="10.0.0.42",
            HTTP_USER_AGENT="ELB-HealthChecker/2.0",
        )

        self.assertEqual(response.status_code, 400)

    def test_livez_is_short_circuited_before_downstream_view(self):
        middleware = HealthcheckHostNormalizationMiddleware(
            lambda _request: HttpResponse("downstream", content_type="text/plain")
        )

        request = self.factory.get("/livez/", HTTP_HOST="test.hive-wiki.com")

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "ok\n")

    def test_non_elb_user_agent_can_still_reach_livez(self):
        response = self.client.get(
            "/livez/",
            HTTP_HOST="10.0.0.42",
            HTTP_USER_AGENT="curl/8.0.1",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "ok\n")

    @patch("config.observability.run_readiness_checks")
    def test_metrics_is_short_circuited_before_host_validation(
        self, run_readiness_checks
    ):
        run_readiness_checks.return_value = {"database": True, "cache": True}

        response = self.client.get(
            "/metrics/",
            HTTP_HOST="10.0.0.42:8000",
        )

        self.assertEqual(response.status_code, 200)
