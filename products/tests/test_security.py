import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from classification.tasks import import_products
from products.models import ProductImport

TEST_MEDIA = tempfile.mkdtemp()


def _read_fixture(filename):
    fixtures_dir = os.path.join(
        os.path.dirname(__file__),
        "fixtures",
    )
    path = os.path.join(fixtures_dir, filename)
    with open(path, "rb") as f:
        return f.read()


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class UploadMimeTypeTest(TestCase):
    def setUp(self):
        self.client = APIClient()

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
        with patch(
            "classification.tasks.start_import_background",
            side_effect=lambda import_id: import_products(import_id),
        ):
            resp = self.client.post(
                "/api/products/import/", {"file": upload}, format="multipart"
            )
        # A declared zip passes the extension check (real .xlsx files are zip
        # containers) but fails xlsx parsing in the background import.
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            ProductImport.objects.get(pk=resp.data["id"]).status,
            ProductImport.Status.FAILED,
        )

    def test_exe_disguised_as_csv_rejected(self):
        upload = SimpleUploadedFile(
            "evil.csv", b"MZ\x90\x00", content_type="application/x-msdownload"
        )
        resp = self.client.post(
            "/api/products/import/", {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
