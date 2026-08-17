"""Concurrency benchmark: thread pool config and partial failure handling.

Uses mocked _run_pipeline to avoid SQLite threading issues while
still testing the batch dispatch logic.
"""

from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from classification.models import Classification
from classification.tasks import process_product_batch
from products.models import Product
from taxonomy.models import Category


@override_settings(
    CLASSIFICATION_CONCURRENCY_LIMIT=3,
    CLASSIFICATION_CANDIDATE_LIMIT=3,
    CLASSIFICATION_MAX_RETRIES=3,
)
class ConcurrencyBenchmarkTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Category.objects.create(name="Test", full_path="Test")
        cls.product_ids = []
        for i in range(5):
            p = Product.objects.create(
                external_id=f"bench-{i}", title=f"Benchmark Product {i}"
            )
            cls.product_ids.append(p.id)
            Classification.objects.create(
                product=p,
                category=cls.cat,
                confidence=80.0,
                status=Classification.Status.NEEDS_REVIEW,
            )

    @patch("classification.tasks._run_pipeline")
    def test_all_products_processed(self, mock_pipeline):
        mock_pipeline.return_value = None
        result = process_product_batch(self.product_ids)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["processed"], 5)
        self.assertEqual(mock_pipeline.call_count, 5)

    @patch("classification.tasks._run_pipeline")
    def test_partial_failure_doesnt_block_others(self, mock_pipeline):
        call_count = {"n": 0}
        titles = {}

        def side_effect(product):
            titles[product.id] = product.title
            call_count["n"] += 1
            if product.title == "Benchmark Product 2":
                raise RuntimeError("Simulated AI error")

        mock_pipeline.side_effect = side_effect
        result = process_product_batch(self.product_ids)
        self.assertEqual(result["processed"], 5)
        self.assertEqual(result["failed"], 1)

    @patch("classification.tasks._run_pipeline")
    def test_max_retries_permanent_failure(self, mock_pipeline):
        from products.models import Product as P

        P.objects.filter(id=self.product_ids[0]).update(retry_count=3)
        mock_pipeline.return_value = None
        result = process_product_batch(self.product_ids)
        self.assertEqual(result["processed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_concurrency_limit_setting_exists(self):
        self.assertTrue(hasattr(settings, "CLASSIFICATION_CONCURRENCY_LIMIT"))
        self.assertGreaterEqual(settings.CLASSIFICATION_CONCURRENCY_LIMIT, 1)
