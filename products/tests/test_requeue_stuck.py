from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone as tz

from products.models import Product

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


class RequeueStuckProductsTest(TestCase):
    def test_stuck_product_requeued(self):
        product = _make_product(
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=45),
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertIsNone(product.processing_started_at)
        self.assertEqual(product.retry_count, 1)

    def test_recently_processing_left_alone(self):
        product = _make_product(
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=10),
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PROCESSING)
        self.assertEqual(product.retry_count, 0)

    def test_already_pending_left_alone(self):
        product = _make_product(status=Product.Status.PENDING)
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.retry_count, 0)

    @override_settings(CLASSIFICATION_MAX_RETRIES=3)
    def test_max_retry_permanently_fails(self):
        product = _make_product(
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=45),
            retry_count=3,
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.FAILED)
        self.assertIsNone(product.processing_started_at)
        self.assertEqual(product.retry_count, 3)
        self.assertIn("Permanently failed", product.error_message)

    @override_settings(CLASSIFICATION_MAX_RETRIES=3)
    def test_below_max_retry_requeued(self):
        product = _make_product(
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=45),
            retry_count=2,
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.retry_count, 3)

    def test_done_product_left_alone(self):
        product = _make_product(
            status=Product.Status.DONE,
            processing_started_at=tz.now() - timedelta(hours=1),
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.DONE)

    def test_failed_product_left_alone(self):
        product = _make_product(
            status=Product.Status.FAILED,
            processing_started_at=tz.now() - timedelta(hours=1),
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.FAILED)

    def test_idempotent_on_rerun(self):
        product = _make_product(
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=45),
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.retry_count, 1)

    def test_multiple_stuck_products(self):
        p1 = _make_product(
            external_id="e1",
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=45),
        )
        p2 = _make_product(
            external_id="e2",
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=45),
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(p1.status, Product.Status.PENDING)
        self.assertEqual(p2.status, Product.Status.PENDING)


class ProcessingStatusTest(TestCase):
    @patch("classification.tasks._run_pipeline_safe")
    def test_products_marked_processing_then_cleared(self, mock_safe):
        p1 = _make_product(external_id="e1")
        p2 = _make_product(external_id="e2")
        mock_safe.side_effect = [
            (p1.id, None),
            (p2.id, None),
        ]

        from classification.tasks import process_product_batch

        process_product_batch([p1.id, p2.id])

        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertIsNone(p1.processing_started_at)
        self.assertIsNone(p2.processing_started_at)
        self.assertEqual(p1.retry_count, 0)
        self.assertEqual(p2.retry_count, 0)

    @patch("classification.tasks._run_pipeline_safe")
    def test_processing_started_at_cleared_on_success(self, mock_safe):
        product = _make_product()
        mock_safe.return_value = (product.id, None)

        from classification.tasks import process_product_batch

        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertIsNone(product.processing_started_at)
        self.assertEqual(product.retry_count, 0)

    @patch("classification.tasks._run_pipeline_safe")
    def test_retry_count_incremented_on_failure(self, mock_safe):
        product = _make_product()
        mock_safe.return_value = (product.id, "fail")

        from classification.tasks import process_product_batch

        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertEqual(product.retry_count, 1)
        self.assertEqual(product.status, Product.Status.PENDING)

    @override_settings(CLASSIFICATION_MAX_RETRIES=2)
    @patch("classification.tasks._run_pipeline_safe")
    def test_permanent_failure_at_max_retries(self, mock_safe):
        product = _make_product(retry_count=1)
        mock_safe.return_value = (product.id, "fail")

        from classification.tasks import process_product_batch

        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertEqual(product.retry_count, 2)
        self.assertEqual(product.status, Product.Status.FAILED)

    def test_empty_batch_returns_zero(self):
        from classification.tasks import process_product_batch

        result = process_product_batch([])
        self.assertEqual(result["processed"], 0)


class SimulateCrashTest(TestCase):
    @patch("classification.tasks._run_pipeline_safe")
    def test_crash_recovery_end_to_end(self, mock_safe):
        """Simulate a worker crash: product stuck in processing, then recovered."""
        from classification.tasks import process_product_batch

        product = _make_product(
            external_id="crash-test",
            title="Leather Sofa",
            description="A brown leather sofa",
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=45),
            retry_count=0,
        )

        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.retry_count, 1)

        mock_safe.return_value = (product.id, None)
        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertIsNone(product.processing_started_at)
        self.assertEqual(product.retry_count, 1)
