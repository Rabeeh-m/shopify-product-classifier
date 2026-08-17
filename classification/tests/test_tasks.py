import json
import os
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from classification.tasks import (
    _run_pipeline,
    _run_pipeline_safe,
    process_all_pending,
    process_product_batch,
)
from products.models import Product

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..",
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)

_NO_DEBUG_TOOLBAR_MIDDLEWARE = [
    m for m in settings.MIDDLEWARE if "debug_toolbar" not in m
]


def _make_product(**kwargs):
    defaults = {
        "external_id": "ext-001",
        "title": "Test Product",
        "description": "A test product",
    }
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


class ProcessProductBatchTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH)

    @patch("classification.tasks._run_pipeline")
    def test_all_products_attempted(self, mock_pipeline):
        p1 = _make_product(external_id="e1", title="Product 1")
        p2 = _make_product(external_id="e2", title="Product 2")
        p3 = _make_product(external_id="e3", title="Product 3")

        process_product_batch([p1.id, p2.id, p3.id])
        self.assertEqual(mock_pipeline.call_count, 3)

    @patch("classification.tasks._run_pipeline")
    def test_failure_does_not_stop_batch(self, mock_pipeline):
        p1 = _make_product(external_id="e1", title="Product 1")
        p2 = _make_product(external_id="e2", title="Product 2")

        mock_pipeline.side_effect = [Exception("boom"), None]
        process_product_batch([p1.id, p2.id])

        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(p1.status, "pending")
        self.assertIn("boom", p1.error_message)
        self.assertEqual(p1.retry_count, 1)
        self.assertEqual(p2.status, "processing")

    @patch("classification.tasks._run_pipeline")
    def test_success_does_not_mark_failed(self, mock_pipeline):
        product = _make_product()
        mock_pipeline.return_value = None

        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertEqual(product.status, "processing")

    @patch("classification.tasks._run_pipeline")
    def test_idempotent_on_done_product(self, mock_pipeline):
        product = _make_product()
        product.status = "done"
        product.save(update_fields=["status"])

        process_product_batch([product.id])
        mock_pipeline.assert_not_called()

    @patch("classification.tasks._run_pipeline")
    def test_processing_status_included(self, mock_pipeline):
        product = _make_product()
        product.status = "processing"
        product.save(update_fields=["status"])

        process_product_batch([product.id])
        mock_pipeline.assert_called_once()

    @patch("classification.tasks._run_pipeline")
    def test_error_message_truncated(self, mock_pipeline):
        product = _make_product()
        long_error = "x" * 1000
        mock_pipeline.side_effect = Exception(long_error)

        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertEqual(len(product.error_message), 500)

    def test_empty_batch_returns_zero(self):
        result = process_product_batch([])
        self.assertEqual(result["processed"], 0)


class ProcessAllPendingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH)

    @patch("classification.tasks.process_product_batch.delay")
    def test_dispatches_pending_products(self, mock_delay):
        _make_product(external_id="e1")
        _make_product(external_id="e2")

        result = process_all_pending(chunk_size=10)
        self.assertEqual(result["processed"], 2)
        mock_delay.assert_called_once()

    @patch("classification.tasks.process_product_batch.delay")
    @patch("classification.tasks.process_all_pending.delay")
    def test_re_enqueues_if_more_pending(self, mock_self_delay, mock_batch_delay):
        for i in range(5):
            _make_product(external_id=f"e{i}")

        process_all_pending(chunk_size=2)
        mock_self_delay.assert_called()

    @patch("classification.tasks.process_product_batch.delay")
    def test_no_pending_returns_zero(self, mock_delay):
        result = process_all_pending()
        self.assertEqual(result["processed"], 0)
        mock_delay.assert_not_called()


class IntegrationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH)

    @patch("classification.services.classifier.call_ai")
    def test_full_pipeline_end_to_end(self, mock_call_ai):
        mock_call_ai.return_value = json.dumps(
            {
                "chosen_category_id": 15,
                "alternatives": [{"category_id": 19, "confidence": 20.0}],
                "attributes": [{"name": "Color", "value": "Brown"}],
                "confidence": 85.0,
                "reasoning": "Sofa classification.",
            }
        )

        product = _make_product(
            title="Leather Sofa", description="A brown leather sofa"
        )

        _run_pipeline(product)

        product.refresh_from_db()
        self.assertIn(product.status, ["done", "needs_review"])
        self.assertEqual(product.classification.category.id, 15)
        self.assertAlmostEqual(product.classification.confidence, 80.0)


class RunPipelineSafeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH)

    @patch("classification.tasks._run_pipeline")
    def test_returns_none_on_success(self, mock_pipeline):
        product = _make_product()
        pid, error = _run_pipeline_safe(product)
        self.assertEqual(pid, product.id)
        self.assertIsNone(error)

    @patch("classification.tasks._run_pipeline")
    def test_returns_error_on_failure(self, mock_pipeline):
        product = _make_product()
        mock_pipeline.side_effect = RuntimeError("AI down")
        pid, error = _run_pipeline_safe(product)
        self.assertEqual(pid, product.id)
        self.assertEqual(error, "AI down")

    @patch("classification.tasks._run_pipeline")
    def test_long_error_truncated(self, mock_pipeline):
        product = _make_product()
        mock_pipeline.side_effect = Exception("x" * 1000)
        pid, error = _run_pipeline_safe(product)
        self.assertEqual(len(error), 500)


@override_settings(
    MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE,
)
class ImportTriggerTest(TestCase):
    @override_settings(
        MEDIA_ROOT=os.path.join(os.path.dirname(__file__), "fixtures"),
    )
    @patch("classification.tasks.process_all_pending.delay")
    def test_import_triggers_task(self, mock_delay):
        from django.contrib.auth.models import User
        from django.core.files.uploadedfile import SimpleUploadedFile

        from products.views import ProductImportCreateView

        csv_data = (
            b"title,description,brand,product_type\n"
            b"Sofa,Leather sofa,Acme,Furniture\n"
        )
        upload = SimpleUploadedFile("test.csv", csv_data, content_type="text/csv")

        from rest_framework.test import APIRequestFactory, force_authenticate

        factory = APIRequestFactory()
        user = User.objects.create_user(username="importer", password="testpass123")
        request = factory.post(
            "/api/products/import/", {"file": upload}, format="multipart"
        )
        force_authenticate(request, user=user)
        view = ProductImportCreateView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 201)
        mock_delay.assert_called_once()
