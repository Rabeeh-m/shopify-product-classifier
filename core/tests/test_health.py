from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

_NO_DEBUG_TOOLBAR_MIDDLEWARE = [
    m for m in settings.MIDDLEWARE if "debug_toolbar" not in m
]


@override_settings(MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE)
class HealthCheckViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_healthy(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "healthy")
        self.assertEqual(resp.data["checks"]["database"], "ok")
        self.assertEqual(resp.data["checks"]["redis"], "ok")
        self.assertEqual(resp["X-Health-Status"], "healthy")

    @patch("core.views._check_database", return_value=False)
    def test_db_failure(self, mock_db):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["status"], "degraded")
        self.assertEqual(resp.data["checks"]["database"], "fail")
        self.assertEqual(resp["X-Health-Status"], "degraded")

    @patch("core.views._check_redis", return_value=False)
    def test_redis_failure(self, mock_redis):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["checks"]["redis"], "fail")
        self.assertEqual(resp["X-Health-Status"], "degraded")

    @patch("core.views._check_database", return_value=False)
    @patch("core.views._check_redis", return_value=False)
    def test_all_down(self, mock_db, mock_redis):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["status"], "degraded")
        self.assertEqual(resp.data["checks"]["database"], "fail")
        self.assertEqual(resp.data["checks"]["redis"], "fail")
