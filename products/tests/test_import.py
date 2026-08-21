import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from classification.tasks import import_products
from products.models import Product, ProductImport
from products.services.import_service import ParseError, validate_and_save_import

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

TEST_MEDIA = tempfile.mkdtemp()


def _read_fixture(filename):
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, "rb") as f:
        return f.read()


def _import_sync(upload, filename):
    """Run the full (non-threaded) import pipeline against an upload."""
    import_obj = validate_and_save_import(upload, filename)
    import_products(import_obj.id)
    import_obj.refresh_from_db()
    return import_obj


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class ImportServiceTest(TestCase):
    def test_valid_csv_creates_products(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_obj = _import_sync(upload, "sample.csv")

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
        import_obj = _import_sync(upload, "sample.xlsx")

        self.assertEqual(import_obj.status, ProductImport.Status.COMPLETED)
        self.assertEqual(import_obj.imported_rows, 3)
        self.assertEqual(Product.objects.count(), 3)

    def test_missing_title_row_skipped_and_logged(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_obj = _import_sync(upload, "sample.csv")

        self.assertEqual(import_obj.failed_rows, 1)
        self.assertEqual(len(import_obj.error_log), 1)
        self.assertEqual(import_obj.error_log[0]["row"], 4)
        self.assertIn("title", import_obj.error_log[0]["error"].lower())

    def test_pipe_separated_images_create_multiple_rows(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        _import_sync(upload, "sample.csv")

        shirt = Product.objects.get(title="Classic T-Shirt")
        self.assertEqual(shirt.images.count(), 2)

    def test_comma_separated_images_create_multiple_rows(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        _import_sync(upload, "sample.csv")

        lamp = Product.objects.get(title="Desk Lamp")
        self.assertEqual(lamp.images.count(), 2)

    def test_missing_required_column_fails_import(self):
        csv_data = b"description,brand\nShirt stuff,Acme\n"
        upload = SimpleUploadedFile("bad.csv", csv_data, content_type="text/csv")
        import_obj = _import_sync(upload, "bad.csv")

        self.assertEqual(import_obj.status, ProductImport.Status.FAILED)
        self.assertTrue(
            any("title" in e["error"].lower() for e in import_obj.error_log)
        )
        self.assertEqual(Product.objects.count(), 0)

    def test_unsupported_file_type_raises_error(self):
        upload = SimpleUploadedFile("bad.txt", b"hello", content_type="text/plain")
        with self.assertRaises(ParseError) as ctx:
            validate_and_save_import(upload, "bad.txt")
        self.assertTrue(any("Unsupported" in e for e in ctx.exception.errors))

    def test_empty_file_imports_zero_products(self):
        csv_data = b"title,description\n"
        upload = SimpleUploadedFile("empty.csv", csv_data, content_type="text/csv")
        import_obj = _import_sync(upload, "empty.csv")
        self.assertEqual(import_obj.imported_rows, 0)
        self.assertEqual(Product.objects.count(), 0)

    def test_products_have_correct_fields(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        _import_sync(upload, "sample.csv")

        shoes = Product.objects.get(title="Running Shoes")
        self.assertEqual(shoes.description, "Lightweight running shoes")
        self.assertEqual(shoes.brand, "FastFeet")
        self.assertEqual(shoes.product_type, "Footwear")

    def test_import_obj_is_created_in_db(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        import_obj = _import_sync(upload, "sample.csv")

        db_obj = ProductImport.objects.get(pk=import_obj.pk)
        self.assertIsNotNone(db_obj.completed_at)

    def test_mapped_headers_create_products(self):
        csv_data = (
            b"Product Name,Product Description ,Collection Name,"
            b"Product Category,Product Number\n"
            b"Empress Sofa,A leather sofa,Empress,Living Room,EEI-1010-WHI\n"
        )
        upload = SimpleUploadedFile("mapped.csv", csv_data, content_type="text/csv")
        import_obj = _import_sync(upload, "mapped.csv")

        self.assertEqual(import_obj.status, ProductImport.Status.COMPLETED)
        self.assertEqual(import_obj.imported_rows, 1)

        product = Product.objects.get(title="Empress Sofa")
        self.assertEqual(product.description, "A leather sofa")
        self.assertEqual(product.brand, "Empress")
        self.assertEqual(product.product_type, "Living Room")
        self.assertEqual(product.external_id, "EEI-1010-WHI")

    def test_mapped_headers_generates_hash_external_id(self):
        csv_data = (
            b"Product Name,Product Description \n"
            b"Empress Chair,A basic chair\n"
        )
        upload = SimpleUploadedFile("nohash.csv", csv_data, content_type="text/csv")
        import_obj = _import_sync(upload, "nohash.csv")

        self.assertEqual(import_obj.status, ProductImport.Status.COMPLETED)
        self.assertEqual(import_obj.imported_rows, 1)

        product = Product.objects.get(title="Empress Chair")
        self.assertTrue(product.external_id.startswith("gen-"))

    def test_products_are_pending_after_import(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("sample.csv", data, content_type="text/csv")
        _import_sync(upload, "sample.csv")
        statuses = set(Product.objects.values_list("status", flat=True))
        self.assertEqual(statuses, {"pending"})


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class ProductImportAPITest(TestCase):
    """API tests run the background work synchronously via patching."""

    def setUp(self):
        self.client = APIClient()

    def _post(self, upload):
        with patch(
            "classification.tasks.start_import_background",
            side_effect=lambda import_id: import_products(import_id),
        ):
            return self.client.post(
                "/api/products/import/", {"file": upload}, format="multipart"
            )

    def test_post_with_valid_csv(self):
        upload = SimpleUploadedFile(
            "sample.csv", _read_fixture("sample_products.csv"), content_type="text/csv"
        )
        response = self._post(upload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["imported_rows"], 3)
        self.assertEqual(Product.objects.count(), 3)

    def test_post_returns_immediately_with_processing_status(self):
        data = _read_fixture("sample_products.csv")
        upload = SimpleUploadedFile("slow.csv", data, content_type="text/csv")
        with patch("classification.tasks.start_import_background") as mock_bg:
            response = self.client.post(
                "/api/products/import/", {"file": upload}, format="multipart"
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_bg.assert_called_once()
        import_id = mock_bg.call_args[0][0]
        self.assertTrue(ProductImport.objects.filter(pk=import_id).exists())

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
        # Header validation happens in the background parse; the upload is
        # accepted but the import record ends up FAILED.
        response = self._post(upload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ProductImport.objects.get(pk=response.data["id"]).status,
                         ProductImport.Status.FAILED)

    def test_get_detail_returns_import(self):
        upload = SimpleUploadedFile(
            "sample.csv", _read_fixture("sample_products.csv"), content_type="text/csv"
        )
        create_resp = self._post(upload)
        import_id = create_resp.data["id"]

        detail_resp = self.client.get(f"/api/products/import/{import_id}/")
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_resp.data["id"], import_id)
        self.assertEqual(detail_resp.data["status"], "completed")

    def test_get_detail_not_found(self):
        response = self.client.get("/api/products/import/99999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_latest_returns_most_recent_import(self):
        first = self._post(
            SimpleUploadedFile(
                "a.csv", _read_fixture("sample_products.csv"), content_type="text/csv"
            )
        )
        second = self._post(
            SimpleUploadedFile(
                "empty.csv", b"title,description\n", content_type="text/csv"
            )
        )
        response = self.client.get("/api/products/import/latest/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], second.data["id"])
        self.assertNotEqual(response.data["id"], first.data["id"])

    def test_latest_returns_404_when_no_imports(self):
        response = self.client.get("/api/products/import/latest/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
