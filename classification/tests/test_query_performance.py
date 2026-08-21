"""Query count regression tests + taxonomy cache invalidation tests."""

import os

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from classification.models import Classification
from classification.services.candidate_finder import find_candidates
from products.models import Product
from taxonomy.models import Category

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..",
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)


class ReviewListQueryCountTest(TestCase):
    """Assert the review list endpoint uses a fixed number of queries."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)
        cat = Category.objects.first()
        for i in range(25):
            p = Product.objects.create(
                external_id=f"ql-{i}",
                title=f"Query Load Product {i}",
            )
            Classification.objects.create(
                product=p,
                category=cat,
                confidence=80.0,
                alternatives=[
                    {"category_id": cat.id, "confidence": 60.0},
                ],
                status=Classification.Status.NEEDS_REVIEW,
            )

    def setUp(self):
        self.client = APIClient()

    def test_review_list_query_count(self):
        """Review list should use <= 5 queries regardless of result count."""
        with self.assertNumQueries(5):
            response = self.client.get("/api/classification/review/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 25)


class CandidateFinderQueryCountTest(TestCase):
    """Assert candidate_finder uses zero DB queries when taxonomy is cached."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)

    def test_find_candidates_uses_cache(self):
        from django.core.cache import cache

        from taxonomy.services.cache import CACHE_KEY

        cache.delete(CACHE_KEY)
        product = Product.objects.create(
            external_id="cf-test", title="Leather Sofa Furniture"
        )
        find_candidates(product)
        with self.assertNumQueries(0):
            find_candidates(product)


class TaxonomyCacheInvalidationTest(TestCase):
    """Verify cache invalidation works after load_taxonomy."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)

    def test_invalidation_causes_cache_miss(self):
        from django.core.cache import cache

        from taxonomy.services.cache import (
            CACHE_KEY,
            get_all_categories,
            invalidate_taxonomy_cache,
        )

        cache.delete(CACHE_KEY)
        cats = get_all_categories()
        self.assertTrue(cache.get(CACHE_KEY) is not None)
        self.assertGreater(len(cats), 0)

        invalidate_taxonomy_cache()
        self.assertIsNone(cache.get(CACHE_KEY))

        cats2 = get_all_categories()
        self.assertEqual(len(cats2), len(cats))

    def test_load_taxonomy_invalidates_cache(self):
        from django.core.cache import cache

        from taxonomy.services.cache import CACHE_KEY, get_all_categories

        cache.delete(CACHE_KEY)
        get_all_categories()
        self.assertIsNotNone(cache.get(CACHE_KEY))

        call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)
        self.assertIsNone(cache.get(CACHE_KEY))
