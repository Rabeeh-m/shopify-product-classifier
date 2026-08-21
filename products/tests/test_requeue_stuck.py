from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone as tz

from products.models import Product


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

    def test_recently_processing_left_alone(self):
        product = _make_product(
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=10),
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PROCESSING)

    def test_already_pending_left_alone(self):
        product = _make_product(status=Product.Status.PENDING)
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)

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

    def test_include_failed_requeues_failed_products(self):
        product = _make_product(
            status=Product.Status.FAILED,
            error_message="AI API error 429",
        )
        call_command("requeue_stuck_products", include_failed=True)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.error_message, "")
        self.assertIsNone(product.processing_started_at)
    def test_include_failed_leaves_done_and_pending(self):
        done = _make_product(external_id="d1", status=Product.Status.DONE)
        pending = _make_product(external_id="p1", status=Product.Status.PENDING)
        call_command("requeue_stuck_products", include_failed=True)
        done.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(done.status, Product.Status.DONE)
        self.assertEqual(pending.status, Product.Status.PENDING)

    def test_idempotent_on_rerun(self):
        product = _make_product(
            status=Product.Status.PROCESSING,
            processing_started_at=tz.now() - timedelta(minutes=45),
        )
        call_command("requeue_stuck_products", older_than_minutes=30)
        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)

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

    @patch("classification.tasks._run_pipeline_safe")
    def test_processing_started_at_cleared_on_success(self, mock_safe):
        product = _make_product()
        mock_safe.return_value = (product.id, None)

        from classification.tasks import process_product_batch

        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertIsNone(product.processing_started_at)

    @patch("classification.tasks._run_pipeline_safe")
    def test_failed_product_marked_failed(self, mock_safe):
        product = _make_product()
        mock_safe.return_value = (product.id, "fail")

        from classification.tasks import process_product_batch

        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.FAILED)
        self.assertEqual(product.error_message, "fail")

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
        )

        call_command("requeue_stuck_products", older_than_minutes=30)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PENDING)

        mock_safe.return_value = (product.id, None)
        process_product_batch([product.id])
        product.refresh_from_db()
        self.assertIsNone(product.processing_started_at)
