import os

from django.core.management import call_command
from django.test import TestCase, override_settings

from classification.models import Classification
from products.models import Product
from taxonomy.models import Category

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..",
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)


@override_settings(CLASSIFICATION_CONFIDENCE_THRESHOLD=70)
class ApproveHighConfidenceCommandTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)
        cls.category = Category.objects.get(name="Armchairs")

    def _make_needs_review(self, external_id, confidence):
        product = Product.objects.create(
            external_id=external_id,
            title=f"Product {external_id}",
            status=Product.Status.NEEDS_REVIEW,
        )
        return Classification.objects.create(
            product=product,
            category=self.category,
            confidence=confidence,
            status=Classification.Status.NEEDS_REVIEW,
        )

    def test_high_confidence_rows_are_approved(self):
        high = self._make_needs_review("high-1", 90.0)

        call_command("approve_high_confidence", verbosity=0)

        high.refresh_from_db()
        self.assertEqual(high.status, Classification.Status.APPROVED)
        self.assertEqual(high.product.status, Product.Status.DONE)
        # Auto-approval is not a human review.
        self.assertIsNone(high.reviewed_at)

    def test_low_confidence_rows_untouched(self):
        low = self._make_needs_review("low-1", 50.0)

        call_command("approve_high_confidence", verbosity=0)

        low.refresh_from_db()
        self.assertEqual(low.status, Classification.Status.NEEDS_REVIEW)
        self.assertEqual(low.product.status, Product.Status.NEEDS_REVIEW)

    def test_threshold_override(self):
        mid = self._make_needs_review("mid-1", 80.0)

        call_command(
            "approve_high_confidence", threshold=85, verbosity=0
        )

        mid.refresh_from_db()
        self.assertEqual(mid.status, Classification.Status.NEEDS_REVIEW)

    def test_dry_run_changes_nothing(self):
        high = self._make_needs_review("dry-1", 90.0)

        call_command("approve_high_confidence", dry_run=True, verbosity=0)

        high.refresh_from_db()
        self.assertEqual(high.status, Classification.Status.NEEDS_REVIEW)
        self.assertEqual(high.product.status, Product.Status.NEEDS_REVIEW)

    def test_failed_products_not_flipped(self):
        product = Product.objects.create(
            external_id="failed-1",
            title="Product failed-1",
            status=Product.Status.FAILED,
        )
        classification = Classification.objects.create(
            product=product,
            category=self.category,
            confidence=90.0,
            status=Classification.Status.NEEDS_REVIEW,
        )

        call_command("approve_high_confidence", verbosity=0)

        classification.refresh_from_db()
        product.refresh_from_db()
        # Classification approves, but the failed product keeps its status.
        self.assertEqual(classification.status, Classification.Status.APPROVED)
        self.assertEqual(product.status, Product.Status.FAILED)
