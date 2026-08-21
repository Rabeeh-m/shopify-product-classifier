import json
import os
import re
import tempfile
from concurrent.futures import Future
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from classification.exceptions import AIClientError
from classification.models import Classification
from products.models import Product
from taxonomy.models import Category

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)

TEST_MEDIA = tempfile.mkdtemp()

_SAMPLE_CSV = (
    b"title,description,brand,product_type\n"
    b"Leather Sofa,A brown leather sofa,Acme,Furniture\n"
    b"Cotton T-Shirt,A basic white shirt,FastFeet,Clothing\n"
    b"Running Shoes,Lightweight running shoes,FastFeet,Footwear\n"
)

_SINGLE_CSV = b"title,description\nLeather Sofa,A brown sofa\n"


def _ai_response_for_category(cat_id, confidence=55.0):
    return json.dumps(
        {
            "chosen_category_id": cat_id,
            "alternatives": [{"category_id": cat_id, "confidence": 60.0}],
            "attributes": [
                {"name": "Color", "value": "Brown"},
                {"name": "Material", "value": "Leather"},
            ],
            "confidence": confidence,
            "reasoning": "Looks like furniture.",
        }
    )


def _run_sync_import(import_id):
    """Run the exact pipeline the background thread would run."""
    from classification.tasks import import_products, process_products

    import_products(import_id)
    process_products(import_id=import_id)


class _InlineExecutor:
    """Drop-in for ThreadPoolExecutor that runs futures on the calling thread.

    Keeps worker DB access on the test connection, avoiding SQLite locking
    between the TestCase transaction and separate worker connections.
    """

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class EndToEndFlowTest(TestCase):
    """Integration test: import -> classify -> review -> approve."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH)

    def setUp(self):
        self.client = APIClient()

    def _upload(self, data, filename="products.csv"):
        upload = SimpleUploadedFile(filename, data, content_type="text/csv")
        with patch(
            "classification.tasks.start_import_background",
            side_effect=_run_sync_import,
        ):
            return self.client.post(
                "/api/products/import/", {"file": upload}, format="multipart"
            )

    def test_full_import_classify_review_approve_flow(self):
        def _mock_call_ai(prompt, **kwargs):
            match = re.search(r"id: (\d+)", prompt)
            first_id = int(match.group(1)) if match else 1
            return _ai_response_for_category(first_id, confidence=55.0)

        with patch(
            "classification.services.classifier.call_ai",
            side_effect=_mock_call_ai,
        ), patch(
            "classification.tasks.ThreadPoolExecutor", _InlineExecutor
        ):
            resp = self._upload(_SAMPLE_CSV)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "completed")
        self.assertEqual(resp.data["imported_rows"], 3)

        # Low mock confidence -> everything lands in the review queue.
        products = list(Product.objects.all().order_by("id"))
        self.assertEqual(len(products), 3)
        for p in products:
            self.assertEqual(p.status, "needs_review")

        classifications = list(
            Classification.objects.select_related("product", "category").all()
        )
        self.assertEqual(len(classifications), 3)
        for cls_obj in classifications:
            self.assertEqual(cls_obj.status, Classification.Status.NEEDS_REVIEW)
            self.assertIsNotNone(cls_obj.category)
            self.assertGreater(cls_obj.confidence, 0)

        list_resp = self.client.get("/api/classification/review/")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.data["count"], 3)

        first_id = list_resp.data["results"][0]["id"]

        detail_resp = self.client.get(f"/api/classification/review/{first_id}/")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertIn("product", detail_resp.data)
        self.assertIn("category", detail_resp.data)

        approve_resp = self.client.post(
            f"/api/classification/review/{first_id}/approve/"
        )
        self.assertEqual(approve_resp.status_code, 200)
        self.assertEqual(approve_resp.data["status"], "approved")

        cls_obj = Classification.objects.get(pk=first_id)
        self.assertEqual(cls_obj.status, Classification.Status.APPROVED)
        self.assertIsNotNone(cls_obj.reviewed_at)
        self.assertEqual(cls_obj.product.status, "done")

        list_resp2 = self.client.get("/api/classification/review/")
        self.assertEqual(list_resp2.data["count"], 2)

    def test_correct_flow_updates_category_and_attributes(self):
        def _mock_call_ai(prompt, **kwargs):
            match = re.search(r"id: (\d+)", prompt)
            first_id = int(match.group(1)) if match else 1
            return _ai_response_for_category(first_id, confidence=55.0)

        with patch(
            "classification.services.classifier.call_ai",
            side_effect=_mock_call_ai,
        ), patch(
            "classification.tasks.ThreadPoolExecutor", _InlineExecutor
        ):
            resp = self._upload(_SINGLE_CSV, "single.csv")
        self.assertEqual(resp.status_code, 201)

        cls_obj = Classification.objects.select_related("category").first()
        self.assertIsNotNone(cls_obj)

        other_cat = Category.objects.exclude(id=cls_obj.category_id).first()

        list_resp = self.client.get("/api/classification/review/")
        cls_id = list_resp.data["results"][0]["id"]

        correct_resp = self.client.post(
            f"/api/classification/review/{cls_id}/correct/",
            {
                "category_id": other_cat.id,
                "attributes": [{"name": "Color", "value": "CustomTeal"}],
            },
            format="json",
        )
        self.assertEqual(correct_resp.status_code, 200)
        self.assertEqual(correct_resp.data["status"], "approved")

        cls_obj.refresh_from_db()
        self.assertEqual(cls_obj.category_id, other_cat.id)
        self.assertEqual(cls_obj.attributes.count(), 1)
        attr = cls_obj.attributes.first()
        self.assertEqual(attr.free_text_value, "CustomTeal")
        self.assertEqual(cls_obj.product.status, "done")

    def test_one_product_failing_does_not_stop_batch(self):
        """An AI failure on one product records FAILED without blocking others."""
        csv_data = (
            b"title,description,brand,product_type\n"
            b"Good Product A,Desc A,Brand A,Type A\n"
            b"Good Product B,Desc B,Brand B,Type B\n"
        )

        def _mock_call_ai(prompt, **kwargs):
            if "Good Product A" in prompt:
                raise RuntimeError("Image download failed")
            match = re.search(r"id: (\d+)", prompt)
            first_id = int(match.group(1)) if match else 1
            return _ai_response_for_category(first_id, confidence=55.0)

        with patch(
            "classification.services.classifier.call_ai",
            side_effect=_mock_call_ai,
        ), patch("classification.tasks.ThreadPoolExecutor", _InlineExecutor):
            resp = self._upload(csv_data, "batch.csv")

        self.assertEqual(resp.status_code, 201)

        product_a = Product.objects.get(title="Good Product A")
        self.assertEqual(product_a.status, Product.Status.FAILED)
        self.assertTrue(product_a.error_message)
        self.assertIsNone(product_a.processing_started_at)

        product_b = Product.objects.get(title="Good Product B")
        self.assertNotEqual(product_b.status, Product.Status.FAILED)
        self.assertIsNone(product_b.processing_started_at)

    def test_rerun_retries_failed_products(self):
        """A second pass picks up FAILED products and clears their errors."""
        csv_data = (
            b"title,description\n"
            b"Recover Me,Some description\n"
        )

        def _failing(prompt, **kwargs):
            raise AIClientError("quota exhausted")

        with patch(
            "classification.services.classifier.call_ai", side_effect=_failing
        ), patch("classification.tasks.ThreadPoolExecutor", _InlineExecutor):
            self._upload(csv_data, "fail.csv")

        product = Product.objects.get(title="Recover Me")
        self.assertEqual(product.status, Product.Status.FAILED)
        self.assertTrue(product.error_message)

        # Quota resets / billing fixed: same command now succeeds.
        def _ok(prompt, **kwargs):
            match = re.search(r"id: (\d+)", prompt)
            first_id = int(match.group(1)) if match else 1
            return _ai_response_for_category(first_id, confidence=55.0)

        from classification.tasks import process_products

        with patch(
            "classification.services.classifier.call_ai", side_effect=_ok
        ), patch("classification.tasks.ThreadPoolExecutor", _InlineExecutor):
            result = process_products()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["failed"], 0)

        product.refresh_from_db()
        self.assertEqual(product.status, "needs_review")
        self.assertEqual(product.error_message, "")
        self.assertIsNotNone(Classification.objects.filter(product=product).first())
