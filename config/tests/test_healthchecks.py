from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings
from django.urls import path


def ok_view(_request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("livez/", ok_view),
    path("dashboard/", ok_view),
]


@override_settings(
    ROOT_URLCONF="config.tests.test_healthchecks",
    ALLOWED_HOSTS=["test.hive-wiki.com"],
)
class HealthcheckHostNormalizationMiddlewareTests(SimpleTestCase):
    def test_elb_healthcheck_ip_host_is_normalized_for_livez(self):
        response = self.client.get(
            "/livez/",
            HTTP_HOST="10.0.0.42",
            HTTP_USER_AGENT="ELB-HealthChecker/2.0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "ok")

    def test_non_healthcheck_path_still_rejects_ip_host(self):
        response = self.client.get(
            "/dashboard/",
            HTTP_HOST="10.0.0.42",
            HTTP_USER_AGENT="ELB-HealthChecker/2.0",
        )

        self.assertEqual(response.status_code, 400)

    def test_non_elb_user_agent_still_rejects_ip_host_for_livez(self):
        response = self.client.get(
            "/livez/",
            HTTP_HOST="10.0.0.42",
            HTTP_USER_AGENT="curl/8.0.1",
        )

        self.assertEqual(response.status_code, 400)
