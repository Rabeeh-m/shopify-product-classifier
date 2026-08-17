import os
import tempfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from products.models import Product, ProductImport
from products.services.import_service import ParseError, import_products

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

TEST_MEDIA = tempfile.mkdtemp()

_NO_DEBUG_TOOLBAR_MIDDLEWARE = [
    m for m in settings.MIDDLEWARE if "debug_toolbar" not in m
]


def _read_fixture(filename):
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, "rb") as f:
        return f.read()


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class ImportServiceTest(TestCase):
    def test_valid_csv_creates_products(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_obj = import_products(upload, "sample.csv")

        self.assertEqual(import_obj.status, ProductImport.Status.COMPLETED)
        self.assertEqual(import_obj.total_rows, 4)
        self.assertEqual(import_obj.imported_rows, 3)
        self.assertEqual(import_obj.failed_rows, 1)
        self.assertEqual(Product.objects.count(), 3)

    def test_valid_xlsx_creates_products(self):
        data = _read_fixture("sample_products.xlsx")
        upload = SimpleUploadedFile(
            "sample.xlsx",
            data,
            content_type=(
                "application/vnd.openxmlformats-officedocument" ".spreadsheetml.sheet"
            ),
        )
        import_obj = import_products(upload, "sample.xlsx")

        self.assertEqual(import_obj.status, ProductImport.Status.COMPLETED)
        self.assertEqual(import_obj.imported_rows, 3)
        self.assertEqual(Product.objects.count(), 3)

    def test_missing_title_row_skipped_and_logged(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_obj = import_products(upload, "sample.csv")

        self.assertEqual(import_obj.failed_rows, 1)
        self.assertEqual(len(import_obj.error_log), 1)
        self.assertEqual(import_obj.error_log[0]["row"], 4)
        self.assertIn("title", import_obj.error_log[0]["error"].lower())

    def test_pipe_separated_images_create_multiple_rows(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_products(upload, "sample.csv")

        shirt = Product.objects.get(title="Classic T-Shirt")
        self.assertEqual(shirt.images.count(), 2)

    def test_comma_separated_images_create_multiple_rows(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_products(upload, "sample.csv")

        lamp = Product.objects.get(title="Desk Lamp")
        self.assertEqual(lamp.images.count(), 2)

    def test_missing_required_column_raises_error(self):
        csv_data = b"description,brand\nShirt stuff,Acme\n"
        upload = SimpleUploadedFile("bad.csv", csv_data, content_type="text/csv")
        with self.assertRaises(ParseError) as ctx:
            import_products(upload, "bad.csv")
        self.assertTrue(any("title" in e for e in ctx.exception.errors))

    def test_unsupported_file_type_raises_error(self):
        upload = SimpleUploadedFile("bad.txt", b"hello", content_type="text/plain")
        with self.assertRaises(ParseError) as ctx:
            import_products(upload, "bad.txt")
        self.assertTrue(any("Unsupported" in e for e in ctx.exception.errors))

    def test_empty_file_imports_zero_products(self):
        csv_data = b"title,description\n"
        upload = SimpleUploadedFile("empty.csv", csv_data, content_type="text/csv")
        import_obj = import_products(upload, "empty.csv")
        self.assertEqual(import_obj.imported_rows, 0)
        self.assertEqual(Product.objects.count(), 0)

    def test_products_have_correct_fields(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_products(upload, "sample.csv")

        shoes = Product.objects.get(title="Running Shoes")
        self.assertEqual(shoes.description, "Lightweight running shoes")
        self.assertEqual(shoes.brand, "FastFeet")
        self.assertEqual(shoes.product_type, "Footwear")

    def test_import_obj_is_created_in_db(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_obj = import_products(upload, "sample.csv")

        db_obj = ProductImport.objects.get(pk=import_obj.pk)
        self.assertIsNotNone(db_obj.completed_at)


@override_settings(
    MEDIA_ROOT=TEST_MEDIA,
    MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE,
)
class ProductImportAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_post_with_valid_csv(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        response = self.client.post(
            "/api/products/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["imported_rows"], 3)
        self.assertEqual(Product.objects.count(), 3)

    def test_post_with_no_file(self):
        response = self.client.post("/api/products/import/", {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_post_with_bad_extension(self):
        upload = SimpleUploadedFile("bad.txt", b"hello", content_type="text/plain")
        response = self.client.post(
            "/api/products/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("errors", response.data)

    def test_post_with_missing_column(self):
        upload = SimpleUploadedFile(
            "bad.csv",
            b"description,brand\nShirt,Acme\n",
            content_type="text/csv",
        )
        response = self.client.post(
            "/api/products/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_detail_returns_import(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        create_resp = self.client.post(
            "/api/products/import/",
            {"file": upload},
            format="multipart",
        )
        import_id = create_resp.data["id"]

        detail_resp = self.client.get(f"/api/products/import/{import_id}/")
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_resp.data["id"], import_id)
        self.assertEqual(detail_resp.data["status"], "completed")

    def test_get_detail_not_found(self):
        response = self.client.get("/api/products/import/99999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
