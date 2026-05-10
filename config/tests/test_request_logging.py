from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.http import HttpResponse, StreamingHttpResponse
from django.test import AsyncClient, SimpleTestCase, override_settings
from django.urls import path

from config.logging import RequestLoggingMiddleware
from config.observability import liveness_probe


async def async_request_id_view(request):
    return HttpResponse(request.request_id, content_type="text/plain")


def streaming_request_id_view(request):
    return StreamingHttpResponse(iter([request.request_id.encode()]))


urlpatterns = [
    path("async-request-id/", async_request_id_view),
    path("streaming-request-id/", streaming_request_id_view),
    path("livez/", liveness_probe),
]


@override_settings(ROOT_URLCONF="config.tests.test_request_logging")
class RequestLoggingMiddlewareTests(SimpleTestCase):
    def test_async_request_path_sets_request_id_header(self):
        response = async_to_sync(AsyncClient().get)("/async-request-id/")

        request_id = response.headers["X-Request-ID"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), request_id)

    def test_streaming_response_sets_request_id_header(self):
        response = self.client.get("/streaming-request-id/")

        request_id = response.headers["X-Request-ID"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content).decode(), request_id)

    def test_healthcheck_path_skips_request_complete_log_by_default(self):
        with patch.object(RequestLoggingMiddleware.logger, "info") as logger_info:
            response = self.client.get("/livez/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response.headers)
        logger_info.assert_not_called()

    @override_settings(DJANGO_LOG_HEALTHCHECKS=True)
    def test_healthcheck_path_logs_when_enabled(self):
        with patch.object(RequestLoggingMiddleware.logger, "info") as logger_info:
            response = self.client.get("/livez/")

        self.assertEqual(response.status_code, 200)
        logger_info.assert_called_once_with("request_complete")
