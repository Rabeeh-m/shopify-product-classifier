import json
import os
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

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

_NO_DEBUG_TOOLBAR_MIDDLEWARE = [
    m for m in settings.MIDDLEWARE if "debug_toolbar" not in m
]

_SAMPLE_CSV = (
    b"title,description,brand,product_type\n"
    b"Leather Sofa,A brown leather sofa,Acme,Furniture\n"
    b"Cotton T-Shirt,A basic white shirt,FastFeet,Clothing\n"
    b"Running Shoes,Lightweight running shoes,FastFeet,Footwear\n"
)

_SINGLE_CSV = b"title,description\nLeather Sofa,A brown sofa\n"


def _mock_ai_response_for_category(cat_id):
    """Build a mock AI response targeting a specific category."""
    return json.dumps(
        {
            "chosen_category_id": cat_id,
            "alternatives": [{"category_id": cat_id, "confidence": 60.0}],
            "attributes": [
                {"name": "Color", "value": "Brown"},
                {"name": "Material", "value": "Leather"},
            ],
            "confidence": 85.0,
            "reasoning": "Looks like furniture.",
        }
    )


@override_settings(
    MEDIA_ROOT=TEST_MEDIA,
    MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE,
)
class EndToEndFlowTest(TestCase):
    """Integration test: import -> classify -> review -> approve.

    Runs the classification pipeline synchronously with a mocked AI
    client, then exercises the review API to approve a result, and
    asserts full database consistency.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH)

    def setUp(self):
        self.client = APIClient()

    def test_full_import_classify_review_approve_flow(self):
        # --- Step 1: Import products ---
        upload = SimpleUploadedFile(
            "products.csv", _SAMPLE_CSV, content_type="text/csv"
        )
        import_resp = self.client.post(
            "/api/products/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(import_resp.status_code, 201)
        self.assertEqual(import_resp.data["imported_rows"], 3)

        products = list(Product.objects.all().order_by("id"))
        self.assertEqual(len(products), 3)
        for p in products:
            self.assertEqual(p.status, "pending")

        # --- Step 2: Classify synchronously with mocked AI ---
        from classification.services.candidate_finder import find_candidates
        from classification.services.classifier import classify_product
        from classification.services.confidence import calculate_confidence
        from classification.services.persistence import save_classification

        def _mock_call_ai(prompt, **kwargs):
            """Return a mock AI response using the first candidate from prompt."""
            import re

            match = re.search(r"id: (\d+)", prompt)
            first_id = int(match.group(1)) if match else 1
            return _mock_ai_response_for_category(first_id)

        with patch(
            "classification.services.classifier.call_ai",
            side_effect=_mock_call_ai,
        ):
            for product in products:
                candidates = find_candidates(product)
                ai_response = classify_product(product, candidates)
                final_confidence = calculate_confidence(product, ai_response)
                save_classification(product, ai_response, final_confidence)

        # Verify classifications created
        classifications = list(
            Classification.objects.select_related("product", "category").all()
        )
        self.assertEqual(len(classifications), 3)
        for cls_obj in classifications:
            self.assertEqual(cls_obj.status, Classification.Status.NEEDS_REVIEW)
            self.assertIsNotNone(cls_obj.category)
            self.assertGreater(cls_obj.confidence, 0)

        # Verify product statuses
        for p in products:
            p.refresh_from_db()
            self.assertIn(p.status, ["done", "needs_review"])

        # --- Step 3: Hit the review list API ---
        list_resp = self.client.get("/api/classification/review/")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.data["count"], 3)

        first_id = list_resp.data["results"][0]["id"]

        # --- Step 4: Get detail for one classification ---
        detail_resp = self.client.get(f"/api/classification/review/{first_id}/")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertIn("product", detail_resp.data)
        self.assertIn("category", detail_resp.data)

        # --- Step 5: Approve it ---
        approve_resp = self.client.post(
            f"/api/classification/review/{first_id}/approve/"
        )
        self.assertEqual(approve_resp.status_code, 200)
        self.assertEqual(approve_resp.data["status"], "approved")

        # Verify DB consistency
        cls_obj = Classification.objects.get(pk=first_id)
        self.assertEqual(cls_obj.status, Classification.Status.APPROVED)
        self.assertIsNotNone(cls_obj.reviewed_at)
        self.assertEqual(cls_obj.product.status, "done")

        # Verify the review list now has 2 remaining
        list_resp2 = self.client.get("/api/classification/review/")
        self.assertEqual(list_resp2.data["count"], 2)

    def test_correct_flow_updates_category_and_attributes(self):
        # Import one product
        upload = SimpleUploadedFile("single.csv", _SINGLE_CSV, content_type="text/csv")
        import_resp = self.client.post(
            "/api/products/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(import_resp.status_code, 201)

        product = Product.objects.first()

        # Classify with mock
        from classification.services.candidate_finder import find_candidates
        from classification.services.classifier import classify_product
        from classification.services.confidence import calculate_confidence
        from classification.services.persistence import save_classification

        def _mock_call_ai(prompt, **kwargs):
            import re

            match = re.search(r"id: (\d+)", prompt)
            first_id = int(match.group(1)) if match else 1
            return _mock_ai_response_for_category(first_id)

        with patch(
            "classification.services.classifier.call_ai",
            side_effect=_mock_call_ai,
        ):
            candidates = find_candidates(product)
            ai_response = classify_product(product, candidates)
            final_confidence = calculate_confidence(product, ai_response)
            cls_obj = save_classification(product, ai_response, final_confidence)

        # Get a different category for correction

        other_cat = Category.objects.exclude(id=cls_obj.category_id).first()

        # Correct with new category and attributes
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
