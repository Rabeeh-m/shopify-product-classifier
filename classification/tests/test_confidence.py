import types

from django.test import TestCase

from classification.services.confidence import calculate_confidence


def _make_product(title="Test", description="A test product", has_image=True):
    """Build a lightweight product-like object for confidence tests."""
    product = types.SimpleNamespace(
        title=title,
        description=description,
    )
    if has_image:
        product.images = types.SimpleNamespace(
            first=lambda: types.SimpleNamespace(url="https://example.com/img.jpg")
        )
    else:
        product.images = types.SimpleNamespace(first=lambda: None)
    return product


def _ai_confidence(value):
    return {"confidence": value}


class FullDataTest(TestCase):
    def test_full_data_passes_through(self):
        product = _make_product(
            title="Leather Sofa", description="Brown leather sofa", has_image=True
        )
        result = calculate_confidence(product, _ai_confidence(90.0))
        self.assertAlmostEqual(result, 90.0)

    def test_high_confidence_unchanged(self):
        product = _make_product(
            title="Shirt", description="Blue cotton shirt", has_image=True
        )
        result = calculate_confidence(product, _ai_confidence(95.0))
        self.assertAlmostEqual(result, 95.0)


class NoDescriptionTest(TestCase):
    def test_no_description_caps_at_65(self):
        product = _make_product(title="Sofa", description="", has_image=True)
        result = calculate_confidence(product, _ai_confidence(90.0))
        self.assertEqual(result, 65.0)

    def test_no_description_already_below_cap(self):
        product = _make_product(title="Sofa", description="", has_image=True)
        result = calculate_confidence(product, _ai_confidence(50.0))
        self.assertEqual(result, 50.0)

    def test_whitespace_description_treated_as_empty(self):
        product = _make_product(title="Sofa", description="   ", has_image=True)
        result = calculate_confidence(product, _ai_confidence(80.0))
        self.assertEqual(result, 65.0)


class TitleOnlyTest(TestCase):
    def test_title_only_caps_at_50(self):
        product = _make_product(title="Widget", description="", has_image=False)
        result = calculate_confidence(product, _ai_confidence(90.0))
        self.assertEqual(result, 50.0)

    def test_title_only_already_below_cap(self):
        product = _make_product(title="Widget", description="", has_image=False)
        result = calculate_confidence(product, _ai_confidence(40.0))
        self.assertEqual(result, 40.0)

    def test_title_only_no_image_no_penalty_stacking(self):
        product = _make_product(title="Widget", description="", has_image=False)
        result = calculate_confidence(product, _ai_confidence(100.0))
        self.assertEqual(result, 50.0)


class NoImagePenaltyTest(TestCase):
    def test_no_image_with_description_penalty(self):
        product = _make_product(title="Sofa", description="Leather", has_image=False)
        result = calculate_confidence(product, _ai_confidence(90.0))
        self.assertEqual(result, 85.0)

    def test_no_image_penalty_does_not_go_below_floor(self):
        product = _make_product(title="Sofa", description="Leather", has_image=False)
        result = calculate_confidence(product, _ai_confidence(35.0))
        self.assertEqual(result, 30.0)

    def test_no_image_on_already_low_score(self):
        product = _make_product(title="Sofa", description="Leather", has_image=False)
        result = calculate_confidence(product, _ai_confidence(50.0))
        self.assertEqual(result, 45.0)


class EdgeCaseTest(TestCase):
    def test_confidence_zero(self):
        product = _make_product(description="Full", has_image=True)
        result = calculate_confidence(product, _ai_confidence(0.0))
        self.assertEqual(result, 0.0)

    def test_confidence_100_full_data(self):
        product = _make_product(title="X", description="Y", has_image=True)
        result = calculate_confidence(product, _ai_confidence(100.0))
        self.assertEqual(result, 100.0)

    def test_confidence_100_title_only(self):
        product = _make_product(title="X", description="", has_image=False)
        result = calculate_confidence(product, _ai_confidence(100.0))
        self.assertEqual(result, 50.0)

    def test_integer_confidence_coerced(self):
        product = _make_product(description="Full", has_image=True)
        result = calculate_confidence(product, _ai_confidence(80))
        self.assertAlmostEqual(result, 80.0)
