import os

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from classification.models import Classification
from products.models import Product, ProductImage
from taxonomy.models import Attribute, AttributeValue, Category, CategoryAttribute

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..",
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)


def _load_taxonomy():
    call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)


def _create_user(username="reviewer"):
    return User.objects.create_user(username=username, password="testpass123")


def _create_product(**kwargs):
    defaults = {
        "external_id": "ext-001",
        "title": "Test Product",
        "description": "A test product",
    }
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


def _create_classification(product, **kwargs):
    defaults = {
        "category": Category.objects.first(),
        "confidence": 75.0,
        "alternatives": [],
        "status": Classification.Status.NEEDS_REVIEW,
    }
    defaults.update(kwargs)
    return Classification.objects.create(product=product, **defaults)


class ReviewListTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        cls.user = _create_user()
        cls.cat = Category.objects.first()

    def setUp(self):
        self.client = APIClient()

    def test_empty_list(self):
        response = self.client.get("/api/classification/review/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_only_needs_review_items(self):
        p1 = _create_product(external_id="e1", title="Pending Product")
        p2 = _create_product(external_id="e2", title="Done Product")
        _create_classification(p1, status=Classification.Status.NEEDS_REVIEW)
        _create_classification(
            p2, status=Classification.Status.APPROVED, reviewed_by=self.user
        )

        response = self.client.get("/api/classification/review/")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["product"]["title"], "Pending Product"
        )

    def test_search_by_title(self):
        p1 = _create_product(external_id="e1", title="Red Leather Sofa")
        p2 = _create_product(external_id="e2", title="Blue Cotton Shirt")
        _create_classification(p1)
        _create_classification(p2)

        response = self.client.get("/api/classification/review/", {"search": "Leather"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["product"]["title"], "Red Leather Sofa"
        )

    def test_filter_by_confidence_range(self):
        p1 = _create_product(external_id="e1", title="High Confidence")
        p2 = _create_product(external_id="e2", title="Low Confidence")
        _create_classification(p1, confidence=85.0)
        _create_classification(p2, confidence=40.0)

        response = self.client.get(
            "/api/classification/review/",
            {"min_confidence": 50, "max_confidence": 100},
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["product"]["title"], "High Confidence"
        )

    def test_pagination(self):
        for i in range(30):
            p = _create_product(external_id=f"e{i}", title=f"Product {i}")
            _create_classification(p)

        response = self.client.get("/api/classification/review/")
        self.assertEqual(response.data["count"], 30)
        self.assertEqual(len(response.data["results"]), 25)

        response2 = self.client.get("/api/classification/review/", {"page": 2})
        self.assertEqual(len(response2.data["results"]), 5)

    def test_serializer_fields(self):
        p = _create_product(external_id="e1", title="Test Product")
        _create_classification(p, confidence=80.0)

        response = self.client.get("/api/classification/review/")
        item = response.data["results"][0]
        self.assertIn("id", item)
        self.assertIn("product", item)
        self.assertIn("category", item)
        self.assertIn("alternatives", item)
        self.assertIn("attributes", item)
        self.assertIn("confidence", item)
        self.assertIn("status", item)
        self.assertEqual(item["product"]["title"], "Test Product")
        self.assertEqual(item["confidence"], 80.0)

    def test_alternatives_include_category_details(self):
        p = _create_product(external_id="e1", title="Test Product")
        cat2 = Category.objects.exclude(id=self.cat.id).first()
        _create_classification(
            p,
            confidence=70.0,
            alternatives=[{"category_id": cat2.id, "confidence": 60.0}],
        )

        response = self.client.get("/api/classification/review/")
        item = response.data["results"][0]
        self.assertEqual(len(item["alternatives"]), 1)
        alt = item["alternatives"][0]
        self.assertEqual(alt["category_id"], cat2.id)
        self.assertIsNotNone(alt["category"])
        self.assertEqual(alt["category"]["id"], cat2.id)


class ReviewDetailTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        cls.user = _create_user()

    def setUp(self):
        self.client = APIClient()

    def test_get_detail(self):
        p = _create_product(external_id="e1", title="Detail Product")
        classification = _create_classification(p, confidence=82.0)

        response = self.client.get(f"/api/classification/review/{classification.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], classification.pk)
        self.assertEqual(response.data["product"]["title"], "Detail Product")
        self.assertEqual(response.data["confidence"], 82.0)

    def test_get_detail_not_found(self):
        response = self.client.get("/api/classification/review/99999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ReviewApproveTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        cls.user = _create_user()

    def setUp(self):
        self.client = APIClient()

    def test_approve_sets_status(self):
        p = _create_product(external_id="e1", title="Approve Me")
        classification = _create_classification(p)

        response = self.client.post(
            f"/api/classification/review/{classification.pk}/approve/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "approved")

        classification.refresh_from_db()
        self.assertEqual(classification.status, Classification.Status.APPROVED)
        self.assertIsNotNone(classification.reviewed_at)

    def test_approve_updates_product_status(self):
        p = _create_product(external_id="e1", title="Approve Me")
        classification = _create_classification(p)

        self.client.post(f"/api/classification/review/{classification.pk}/approve/")
        p.refresh_from_db()
        self.assertEqual(p.status, "done")

    def test_approve_already_reviewed_returns_409(self):
        p = _create_product(external_id="e1")
        classification = _create_classification(
            p,
            status=Classification.Status.APPROVED,
            reviewed_by=self.user,
        )

        response = self.client.post(
            f"/api/classification/review/{classification.pk}/approve/"
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("error", response.data)

    def test_approve_not_found(self):
        response = self.client.post("/api/classification/review/99999/approve/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ReviewCorrectTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        cls.user = _create_user()
        cls.cat = Category.objects.first()
        cls.attr, _ = Attribute.objects.get_or_create(name="ReviewTestColor")
        cls.attr_value, _ = AttributeValue.objects.get_or_create(
            attribute=cls.attr, value="ReviewRed"
        )
        CategoryAttribute.objects.get_or_create(category=cls.cat, attribute=cls.attr)

    def setUp(self):
        self.client = APIClient()

    def test_correct_with_new_category(self):
        p = _create_product(external_id="e1", title="Correct Me")
        classification = _create_classification(p)
        new_cat = Category.objects.exclude(id=self.cat.id).first()

        response = self.client.post(
            f"/api/classification/review/{classification.pk}/correct/",
            {"category_id": new_cat.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "approved")
        self.assertEqual(response.data["category"]["id"], new_cat.id)
        self.assertIn("correction_notes", response.data)
        self.assertNotEqual(response.data["correction_notes"], "")

        classification.refresh_from_db()
        self.assertEqual(classification.category, new_cat)
        self.assertEqual(classification.status, Classification.Status.APPROVED)

    def test_correct_with_attributes(self):
        p = _create_product(external_id="e1", title="Correct Attributes")
        classification = _create_classification(p)

        response = self.client.post(
            f"/api/classification/review/{classification.pk}/correct/",
            {"attributes": [{"name": "ReviewTestColor", "value": "ReviewRed"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        classification.refresh_from_db()
        attrs = classification.attributes.all()
        self.assertEqual(attrs.count(), 1)
        self.assertEqual(attrs.first().attribute.name, "ReviewTestColor")
        self.assertEqual(attrs.first().value.value, "ReviewRed")

    def test_correct_invalid_category_returns_400(self):
        p = _create_product(external_id="e1")
        classification = _create_classification(p)

        response = self.client.post(
            f"/api/classification/review/{classification.pk}/correct/",
            {"category_id": 99999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_correct_invalid_attribute_returns_400(self):
        p = _create_product(external_id="e1")
        classification = _create_classification(p)

        response = self.client.post(
            f"/api/classification/review/{classification.pk}/correct/",
            {"attributes": [{"name": "NonExistent", "value": "Something"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_correct_already_reviewed_returns_400(self):
        p = _create_product(external_id="e1")
        classification = _create_classification(
            p,
            status=Classification.Status.APPROVED,
            reviewed_by=self.user,
        )

        response = self.client.post(
            f"/api/classification/review/{classification.pk}/correct/",
            {"category_id": self.cat.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_correct_updates_product_status(self):
        p = _create_product(external_id="e1")
        classification = _create_classification(p)
        new_cat = Category.objects.exclude(id=self.cat.id).first()

        self.client.post(
            f"/api/classification/review/{classification.pk}/correct/",
            {"category_id": new_cat.id},
            format="json",
        )
        p.refresh_from_db()
        self.assertEqual(p.status, "done")

    def test_correct_not_found(self):
        response = self.client.post(
            "/api/classification/review/99999/correct/",
            {"category_id": self.cat.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_correct_preserves_original_ai_alternatives(self):
        p = _create_product(external_id="e1")
        alt_cat = Category.objects.exclude(id=self.cat.id).first()
        classification = _create_classification(
            p,
            alternatives=[{"category_id": alt_cat.id, "confidence": 55.0}],
        )
        new_cat = Category.objects.exclude(id__in=[self.cat.id, alt_cat.id]).first()

        self.client.post(
            f"/api/classification/review/{classification.pk}/correct/",
            {"category_id": new_cat.id},
            format="json",
        )

        response = self.client.get(f"/api/classification/review/{classification.pk}/")
        self.assertEqual(len(response.data["alternatives"]), 1)
        self.assertEqual(response.data["alternatives"][0]["category_id"], alt_cat.id)


class ClassifiedProductDetailTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        cls.cat = Category.objects.first()

    def setUp(self):
        self.client = APIClient()

    def test_get_detail_includes_full_product(self):
        p = Product.objects.create(
            external_id="pd-001",
            title="Detailed Product",
            description="A full description",
            brand="Acme",
            product_type="Sofa",
            raw_data={"sku": "ACME-1", "color": "Red"},
        )
        classification = _create_classification(p, confidence=88.0)

        response = self.client.get(
            f"/api/classification/products/{classification.pk}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], classification.pk)

        product = response.data["product"]
        self.assertEqual(product["title"], "Detailed Product")
        self.assertEqual(product["description"], "A full description")
        self.assertEqual(product["brand"], "Acme")
        self.assertEqual(product["product_type"], "Sofa")
        self.assertEqual(product["external_id"], "pd-001")
        self.assertEqual(product["raw_data"], {"sku": "ACME-1", "color": "Red"})
        self.assertIn("images", product)
        self.assertIn("created_at", product)
        self.assertIn("updated_at", product)

        self.assertEqual(response.data["confidence"], 88.0)
        self.assertEqual(response.data["category"]["id"], self.cat.id)

    def test_get_detail_includes_images(self):
        p = Product.objects.create(
            external_id="pd-img", title="Product With Image"
        )
        ProductImage.objects.create(product=p, url="/media/pd-img.jpg")
        classification = _create_classification(p)

        response = self.client.get(
            f"/api/classification/products/{classification.pk}/"
        )
        product = response.data["product"]
        self.assertEqual(len(product["images"]), 1)
        self.assertTrue(product["images"][0].endswith("/media/pd-img.jpg"))

    def test_get_detail_not_found(self):
        response = self.client.get("/api/classification/products/99999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
