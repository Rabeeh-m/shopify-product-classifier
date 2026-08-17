import os
import types

from django.core.management import call_command
from django.test import TestCase

from classification.services.candidate_finder import (
    CandidateResult,
    _simple_stem,
    _tokenize,
    find_candidates,
)
from products.models import Product
from taxonomy.models import Category

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)


def _make_product(**kwargs):
    """Create an in-memory product-like object without DB."""
    return types.SimpleNamespace(
        title=kwargs.get("title", ""),
        description=kwargs.get("description", ""),
        product_type=kwargs.get("product_type", ""),
    )


class StemmerTest(TestCase):
    def test_plurals(self):
        self.assertEqual(_simple_stem("sofas"), "sofa")
        self.assertEqual(_simple_stem("shirts"), "shirt")
        self.assertEqual(_simple_stem("tables"), "table")

    def test_ies_ending(self):
        self.assertEqual(_simple_stem("ies"), "y")
        self.assertEqual(_simple_stem("ies"), "y")

    def test_ing_ending(self):
        self.assertEqual(_simple_stem("running"), "runn")
        self.assertEqual(_simple_stem("walking"), "walk")

    def test_short_words_unchanged(self):
        self.assertEqual(_simple_stem("ss"), "ss")
        self.assertEqual(_simple_stem("is"), "is")

    def test_already_stemmed(self):
        self.assertEqual(_simple_stem("sofa"), "sofa")
        self.assertEqual(_simple_stem("shirt"), "shirt")


class TokenizeTest(TestCase):
    def test_basic(self):
        tokens = _tokenize("Leather Sofa")
        self.assertIn("leather", tokens)
        self.assertIn("sofa", tokens)

    def test_stop_words_removed(self):
        tokens = _tokenize("the big sofa")
        self.assertNotIn("the", tokens)
        self.assertIn("big", tokens)
        self.assertIn("sofa", tokens)

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), set())

    def test_none(self):
        self.assertEqual(_tokenize(None), set())

    def test_short_words_filtered(self):
        tokens = _tokenize("a big red")
        self.assertNotIn("a", tokens)


class CandidateFinderUnitTest(TestCase):
    """Tests using in-memory objects — no database required."""

    def test_leather_sofa_ranks_sofa_category_top(self):
        cat = Category(
            name="Sofas & Loveseats",
            full_path="Furniture > Sofas & Loveseats",
        )
        product = _make_product(title="Leather Sofa")
        results = find_candidates(product, categories=[cat], limit=10)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0].category, cat)
        self.assertGreater(results[0].score, 0)

    def test_multiple_categories_ranked(self):
        cats = [
            Category(
                name="Sofas & Loveseats", full_path="Furniture > Sofas & Loveseats"
            ),
            Category(name="Laptops", full_path="Electronics > Computers > Laptops"),
            Category(name="T-Shirts", full_path="Clothing > Tops > T-Shirts"),
        ]
        product = _make_product(title="Leather Sofa")
        results = find_candidates(product, categories=cats, limit=10)
        self.assertEqual(results[0].category.name, "Sofas & Loveseats")

    def test_description_boosts_score(self):
        cat = Category(
            name="Sofas & Loveseats",
            full_path="Furniture > Sofas & Loveseats",
        )
        bare = _make_product(title="Sofas")
        with_desc = _make_product(
            title="Sofas",
            description="A comfortable loveseat for the living room",
        )
        score_bare = find_candidates(bare, categories=[cat], limit=1)[0].score
        score_desc = find_candidates(with_desc, categories=[cat], limit=1)[0].score
        self.assertGreater(score_desc, score_bare)

    def test_empty_product_returns_empty(self):
        cat = Category(name="Sofas", full_path="Furniture > Sofas")
        product = _make_product(title="", description="", product_type="")
        results = find_candidates(product, categories=[cat], limit=10)
        self.assertEqual(results, [])

    def test_limit_respected(self):
        cats = [
            Category(name=f"Cat {i}", full_path=f"Root > Cat {i}") for i in range(20)
        ]
        product = _make_product(title="Cat")
        results = find_candidates(product, categories=cats, limit=5)
        self.assertEqual(len(results), 5)

    def test_no_matching_categories_returns_empty(self):
        cats = [
            Category(name="Laptops", full_path="Electronics > Laptops"),
        ]
        product = _make_product(title="Leather Sofa")
        results = find_candidates(product, categories=cats, limit=10)
        self.assertEqual(results, [])

    def test_result_is_namedtuple(self):
        cat = Category(name="Sofas", full_path="Furniture > Sofas")
        product = _make_product(title="Sofa")
        results = find_candidates(product, categories=[cat], limit=1)
        self.assertIsInstance(results[0], CandidateResult)
        self.assertTrue(hasattr(results[0], "category"))
        self.assertTrue(hasattr(results[0], "score"))


class CandidateFinderIntegrationTest(TestCase):
    """Tests against the real database with loaded taxonomy."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("load_taxonomy", source=FIXTURE_PATH)

    def test_leather_sofa_ranks_near_top(self):
        product = Product.objects.create(
            title="Leather Sofa",
            description="Comfortable brown leather sofa for the living room",
            product_type="Furniture",
        )
        results = find_candidates(product)
        names = [r.category.name for r in results]
        self.assertIn("Sofas & Loveseats", names)
        idx = names.index("Sofas & Loveseats")
        self.assertLessEqual(
            idx,
            3,
            (
                f"'Sofas & Loveseats' ranked {idx + 1}, expected top 3. "
                f"Top results: {names[:5]}"
            ),
        )

    def test_title_only_still_returns_results(self):
        product = Product.objects.create(title="Running Shoes")
        results = find_candidates(product)
        self.assertGreater(len(results), 0)

    def test_limit_5_returns_at_most_5(self):
        product = Product.objects.create(title="Sofa")
        results = find_candidates(product, limit=5)
        self.assertLessEqual(len(results), 5)

    def test_no_description_returns_results(self):
        product = Product.objects.create(title="Wireless Headphones")
        results = find_candidates(product)
        self.assertGreater(len(results), 0)
        names = [r.category.name for r in results]
        self.assertIn("Headphones", names)

    def test_product_type_helps_ranking(self):
        product = Product.objects.create(
            title="Classic",
            description="A timeless design",
            product_type="T-Shirt",
        )
        results = find_candidates(product, limit=10)
        names = [r.category.name for r in results]
        self.assertIn("T-Shirts", names)

    def test_headphones_product_type_ranking(self):
        product = Product.objects.create(
            title="Sony WH-1000XM5",
            description="Wireless noise cancelling headphones",
            product_type="Headphones",
        )
        results = find_candidates(product, limit=10)
        names = [r.category.name for r in results]
        self.assertIn("Headphones", names)

    def test_scores_are_positive(self):
        product = Product.objects.create(title="Jacket")
        results = find_candidates(product)
        for r in results:
            self.assertGreater(r.score, 0)
