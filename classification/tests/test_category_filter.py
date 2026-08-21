import os

from django.core.management import call_command
from django.db.models import Count
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

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


def _load_taxonomy():
    call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)


def _create_product(title, external_id=None):
    return Product.objects.create(
        external_id=external_id or f"ext-{title[:10]}",
        title=title,
        description="test",
    )


def _create_classification(product, category, conf=80.0):
    return Classification.objects.create(
        product=product,
        category=category,
        confidence=conf,
        alternatives=[],
        status=Classification.Status.APPROVED,
    )


class ClassifiedProductsCategoryFilterTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        # Pick a root with at least two children plus one of its subcategories
        cls.root = (
            Category.objects.filter(children__isnull=False)
            .annotate(n=Count("children"))
            .filter(n__gte=2)
            .first()
        )
        cls.sub = Category.objects.filter(parent=cls.root).first()
        cls.other_sub = (
            Category.objects.filter(parent=cls.root)
            .exclude(pk=cls.sub.pk)
            .first()
        )
        cls.unrelated = Category.objects.exclude(
            pk__in=[cls.root.pk, cls.sub.pk, cls.other_sub.pk]
        ).first()

    def setUp(self):
        self.client = APIClient()

    def _seed(self):
        in_sub = _create_product("In Sub")
        in_other_sub = _create_product("In Other Sub")
        direct_root = _create_product("Direct Root")
        outside = _create_product("Outside")
        _create_classification(in_sub, self.sub)
        _create_classification(in_other_sub, self.other_sub)
        _create_classification(direct_root, self.root)
        _create_classification(outside, self.unrelated)
        return {in_sub, in_other_sub, direct_root, outside}

    def test_root_filter_includes_descendants(self):
        self._seed()
        resp = self.client.get(
            f"/api/classification/products/?category={self.root.pk}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        titles = {r["product"]["title"] for r in resp.data["results"]}
        self.assertEqual(titles, {"In Sub", "In Other Sub", "Direct Root"})
        self.assertEqual(resp.data["count"], 3)

    def test_leaf_filter_exact_only(self):
        self._seed()
        resp = self.client.get(
            f"/api/classification/products/?category={self.sub.pk}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        titles = {r["product"]["title"] for r in resp.data["results"]}
        self.assertEqual(titles, {"In Sub"})

    def test_unknown_category_returns_400(self):
        resp = self.client.get("/api/classification/products/?category=999999")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_numeric_category_returns_400(self):
        resp = self.client.get("/api/classification/products/?category=abc")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_category_param_returns_all(self):
        self._seed()
        resp = self.client.get("/api/classification/products/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 4)


class ClassifiedProductsAvailableCategoriesTest(TestCase):
    """Options must be generated from the listed products, not the taxonomy."""

    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        cls.root_a = (
            Category.objects.filter(children__isnull=False)
            .annotate(n=Count("children"))
            .filter(n__gte=2)
            .first()
        )
        cls.sub_a1 = Category.objects.filter(parent=cls.root_a).first()
        cls.sub_a2 = (
            Category.objects.filter(parent=cls.root_a)
            .exclude(pk=cls.sub_a1.pk)
            .first()
        )
        cls.root_b = Category.objects.filter(parent__isnull=True).exclude(
            pk=cls.root_a.pk
        ).first()
        # A leaf with no products at all (must never appear in options)
        cls.empty_leaf = Category.objects.exclude(
            pk__in=[
                cls.root_a.pk,
                cls.sub_a1.pk,
                cls.sub_a2.pk,
                cls.root_b.pk,
            ]
        ).first()

    def setUp(self):
        self.client = APIClient()

    def _seed(self):
        p1 = _create_product("P1")
        p2 = _create_product("P2")
        p3 = _create_product("P3")
        _create_classification(p1, self.sub_a1)
        _create_classification(p2, self.sub_a1)
        _create_classification(p3, self.sub_a2)

    def test_options_derived_from_products_with_counts(self):
        self._seed()
        resp = self.client.get("/api/classification/products/")
        tree = resp.data["available_categories"]

        ids = {entry["id"] for entry in tree}
        self.assertIn(self.root_a.id, ids)
        self.assertNotIn(self.empty_leaf.id, ids)

        entry_a = next(e for e in tree if e["id"] == self.root_a.id)
        self.assertEqual(entry_a["count"], 3)
        child_counts = {c["id"]: c["count"] for c in entry_a["children"]}
        self.assertEqual(child_counts[self.sub_a1.id], 2)
        self.assertEqual(child_counts[self.sub_a2.id], 1)

    def test_options_respect_search_and_status_filters(self):
        self._seed()
        resp = self.client.get("/api/classification/products/?search=P1")
        tree = resp.data["available_categories"]
        entry_a = next(e for e in tree if e["id"] == self.root_a.id)
        self.assertEqual(entry_a["count"], 1)
        self.assertEqual(len(entry_a["children"]), 1)
        self.assertEqual(entry_a["children"][0]["id"], self.sub_a1.id)

    def test_options_stable_while_category_selected(self):
        self._seed()
        resp = self.client.get(
            f"/api/classification/products/?category={self.sub_a1.pk}"
        )
        self.assertEqual(resp.data["count"], 2)
        # Options still cover the other subcategory so users can switch
        tree = resp.data["available_categories"]
        entry_a = next(e for e in tree if e["id"] == self.root_a.id)
        self.assertEqual(len(entry_a["children"]), 2)

    def test_empty_result_set_yields_empty_options(self):
        resp = self.client.get("/api/classification/products/")
        self.assertEqual(resp.data["available_categories"], [])


class ClassifiedProductsPageSizeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        cls.cat = Category.objects.first()

    def setUp(self):
        self.client = APIClient()

    def test_twenty_products_per_page(self):
        for i in range(25):
            product = _create_product(f"Bulk {i}", external_id=f"bulk-{i}")
            _create_classification(product, self.cat)

        resp = self.client.get("/api/classification/products/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 25)
        self.assertEqual(len(resp.data["results"]), 20)
