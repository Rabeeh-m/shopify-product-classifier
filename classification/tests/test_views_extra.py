from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from products.models import Product

_NO_DEBUG_TOOLBAR_MIDDLEWARE = [
    m for m in settings.MIDDLEWARE if "debug_toolbar" not in m
]


@override_settings(MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE)
class ClassificationJobStatusViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_empty_database(self):
        response = self.client.get("/api/classification/jobs/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)
        self.assertEqual(response.data["pending"], 0)
        self.assertEqual(response.data["done"], 0)

    def test_with_products_in_various_statuses(self):
        for i, status_val in enumerate(
            ["pending", "processing", "done", "needs_review", "failed"]
        ):
            Product.objects.create(
                external_id=f"ext-{i}",
                title=f"Product {i}",
                status=status_val,
            )
        Product.objects.create(
            external_id="ext-5", title="Another pending", status="pending"
        )

        response = self.client.get("/api/classification/jobs/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 6)
        self.assertEqual(response.data["pending"], 2)
        self.assertEqual(response.data["processing"], 1)
        self.assertEqual(response.data["done"], 1)
        self.assertEqual(response.data["needs_review"], 1)
        self.assertEqual(response.data["failed"], 1)


@override_settings(MIDDLEWARE=_NO_DEBUG_TOOLBAR_MIDDLEWARE)
class ReviewListViewUnpagedTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_fewer_than_page_size_returns_list(self):
        from classification.models import Classification
        from taxonomy.models import Category

        Category.objects.create(id=999, name="Test", full_path="Test")
        cat = Category.objects.get(id=999)
        for i in range(3):
            p = Product.objects.create(external_id=f"ext-{i}", title=f"P{i}")
            Classification.objects.create(
                product=p,
                category=cat,
                confidence=80.0,
                status=Classification.Status.NEEDS_REVIEW,
            )

        response = self.client.get("/api/classification/review/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertIn("results", response.data)
