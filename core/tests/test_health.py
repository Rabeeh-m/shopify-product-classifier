from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient


class HealthCheckViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_healthy(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "ok")

    @patch("core.views.connection")
    def test_db_failure(self, mock_connection):
        mock_connection.cursor.side_effect = Exception("DB down")
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["status"], "error")
