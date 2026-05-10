import logging

from django.test import SimpleTestCase, override_settings

from config.logging import SuppressHealthcheckAccessLogsFilter


class SuppressHealthcheckAccessLogsFilterTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.filter = SuppressHealthcheckAccessLogsFilter()

    def test_suppresses_hivewiki_request_completion_for_healthcheck(self):
        record = logging.LogRecord(
            name="hivewiki.request",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="request_complete",
            args=(),
            exc_info=None,
        )
        record.path = "/livez/"

        self.assertFalse(self.filter.filter(record))

    def test_keeps_hivewiki_request_failures_for_healthcheck(self):
        record = logging.LogRecord(
            name="hivewiki.request",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="request_failed",
            args=(),
            exc_info=None,
        )
        record.path = "/readyz/"

        self.assertTrue(self.filter.filter(record))

    def test_suppresses_uvicorn_access_log_for_healthcheck(self):
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:54321", "GET", "/readyz/", "1.1", 200),
            exc_info=None,
        )

        self.assertFalse(self.filter.filter(record))

    def test_suppresses_django_server_access_log_for_healthcheck(self):
        record = logging.LogRecord(
            name="django.server",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='"%s" %s %s',
            args=("GET /livez/ HTTP/1.1", 200, 3),
            exc_info=None,
        )

        self.assertFalse(self.filter.filter(record))

    def test_keeps_uvicorn_access_log_for_non_healthcheck(self):
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:54321", "GET", "/dashboard/", "1.1", 200),
            exc_info=None,
        )

        self.assertTrue(self.filter.filter(record))

    @override_settings(DJANGO_LOG_HEALTHCHECKS=True)
    def test_can_enable_healthcheck_access_logs(self):
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:54321", "GET", "/livez/", "1.1", 200),
            exc_info=None,
        )

        self.assertTrue(self.filter.filter(record))
