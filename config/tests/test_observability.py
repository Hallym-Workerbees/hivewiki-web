from unittest.mock import patch

from django.test import SimpleTestCase

from config.observability import reset_metrics


class ObservabilityViewsTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        reset_metrics()

    def test_liveness_probe_returns_ok(self):
        response = self.client.get("/livez/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        self.assertEqual(response.content.decode(), "ok\n")

    @patch("config.observability.run_readiness_checks")
    def test_readiness_probe_returns_ready_when_all_checks_pass(
        self, run_readiness_checks
    ):
        run_readiness_checks.return_value = {"database": True, "cache": True}

        response = self.client.get("/readyz/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "ready\n")

    @patch("config.observability.run_readiness_checks")
    def test_readiness_probe_returns_503_with_failed_checks(self, run_readiness_checks):
        run_readiness_checks.return_value = {"database": False, "cache": True}

        response = self.client.get("/readyz/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content.decode(), "not ready: database\n")

    @patch("config.observability.run_readiness_checks")
    def test_metrics_view_renders_prometheus_text_format(self, run_readiness_checks):
        run_readiness_checks.return_value = {"database": True, "cache": False}

        response = self.client.get("/metrics/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "text/plain; version=0.0.4; charset=utf-8",
        )
        content = response.content.decode()
        self.assertIn(
            "# HELP hivewiki_up Whether the Django process is running.", content
        )
        self.assertIn('hivewiki_readiness_check{check="database"} 1', content)
        self.assertIn('hivewiki_readiness_check{check="cache"} 0', content)
        self.assertIn("hivewiki_ready 0", content)

    @patch("config.observability.run_readiness_checks")
    def test_metrics_view_includes_http_request_metrics(self, run_readiness_checks):
        run_readiness_checks.return_value = {"database": True, "cache": True}

        self.client.get("/livez/")
        response = self.client.get("/metrics/")

        content = response.content.decode()
        self.assertIn(
            'hivewiki_http_requests_total{method="GET",route="/livez/"} 1', content
        )
        self.assertIn(
            'hivewiki_http_responses_total{method="GET",route="/livez/",status_code="200"} 1',
            content,
        )
        self.assertIn(
            'hivewiki_http_request_duration_seconds_count{method="GET",route="/livez/"} 1',
            content,
        )
