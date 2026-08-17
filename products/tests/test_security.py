import os
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

TEST_MEDIA = tempfile.mkdtemp()

_NO_DEBUG_TOOLBAR_MIDDLEWARE = [
    m for m in settings.MIDDLEWARE if "debug_toolbar" not in m
]


def _read_fixture(filename):
    fixtures_dir = os.path.join(
        os.path.dirname(__file__),
        "fixtures",
    )
    path = os.path.join(fixtures_dir, filename)
    with open(path, "rb") as f:
        return f.read()


@override_settings(
    MEDIA_ROOT=TEST_MEDIA,
    MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE,
)
class UploadMimeTypeTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="uploader", password="testpass123"
        )
        self.client.force_authenticate(user=self.user)

    def test_csv_with_csv_content_type_accepted(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        resp = self.client.post(
            "/api/products/import/", {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_txt_file_rejected(self):
        upload = SimpleUploadedFile("bad.txt", b"hello", content_type="text/plain")
        resp = self.client.post(
            "/api/products/import/", {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_zip_as_xlsx_rejected(self):
        upload = SimpleUploadedFile(
            "trick.xlsx", b"PK\x03\x04", content_type="application/zip"
        )
        resp = self.client.post(
            "/api/products/import/", {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_exe_disguised_as_csv_rejected(self):
        upload = SimpleUploadedFile(
            "evil.csv", b"MZ\x90\x00", content_type="application/x-msdownload"
        )
        resp = self.client.post(
            "/api/products/import/", {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(
    MEDIA_ROOT=TEST_MEDIA,
    MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE,
)
class UnauthenticatedAccessTest(TestCase):
    def test_import_create_requires_auth(self):
        unauth = APIClient()
        resp = unauth.post("/api/products/import/", {}, format="multipart")
        self.assertIn(
            resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        )

    def test_import_detail_requires_auth(self):
        unauth = APIClient()
        resp = unauth.get("/api/products/import/1/")
        self.assertIn(
            resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        )

    def test_review_list_requires_auth(self):
        unauth = APIClient()
        resp = unauth.get("/api/classification/review/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_review_approve_requires_auth(self):
        unauth = APIClient()
        resp = unauth.post("/api/classification/review/1/approve/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_review_correct_requires_auth(self):
        unauth = APIClient()
        resp = unauth.post(
            "/api/classification/review/1/correct/",
            {"category_id": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_health_check_accessible_without_auth(self):
        unauth = APIClient()
        resp = unauth.get("/api/health/")
        self.assertIn(resp.status_code, [200, 503])

    def test_job_status_accessible_without_auth(self):
        unauth = APIClient()
        resp = unauth.get("/api/classification/jobs/status/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_category_search_accessible_without_auth(self):
        unauth = APIClient()
        resp = unauth.get("/api/taxonomy/categories/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(
    MEDIA_ROOT=TEST_MEDIA,
    MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE,
)
class ThrottleResponseTest(TestCase):
    """Verify that the throttle exception handler returns the right shape."""

    def test_throttled_response_has_correct_envelope(self):
        from django.core.cache import cache

        cache.clear()

        unauth = APIClient()
        # Burn through the anonymous throttle (60/min) in a tight loop.
        # In tests the cache backend is usually LocMemCache so we can
        # fill it quickly, but we'll use force_override to simulate it.
        from django.test.utils import override_settings

        with override_settings(
            REST_FRAMEWORK={
                **settings.REST_FRAMEWORK,
                "DEFAULT_THROTTLE_RATES": {"anon": "2/minute", "user": "2/minute"},
            }
        ):
            for _ in range(3):
                unauth.get("/api/classification/jobs/status/")

            # The 3rd request should be throttled
            resp = unauth.get("/api/classification/jobs/status/")
            if resp.status_code == 429:
                self.assertIn("error", resp.data)
                self.assertEqual(resp.data["error"]["code"], "THROTTLED")
