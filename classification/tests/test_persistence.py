import os

from django.core.management import call_command
from django.test import TestCase, override_settings

from classification.models import Classification, ClassificationAttribute
from classification.services.persistence import (
    _resolve_attribute,
    save_classification,
)
from products.models import Product
from taxonomy.models import Attribute, Category

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..",
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)


def _ai_response(category_id=15, attributes=None, confidence=85.0):
    """Return a minimal valid AI response dict."""
    return {
        "chosen_category_id": category_id,
        "alternatives": [{"category_id": 19, "confidence": 20.0}],
        "attributes": attributes
        or [
            {"name": "Color", "value": "Brown"},
            {"name": "Material", "value": "Leather"},
        ],
        "confidence": confidence,
        "reasoning": "Looks like a sofa.",
    }


class ResolveAttributeTest(TestCase):
    def _resolve(self, ai_attr):
        return _resolve_attribute(ai_attr)

    def test_existing_attribute_resolves(self):
        call_command("load_taxonomy", source=FIXTURE_PATH)
        attr_obj, value_obj, free_text = self._resolve(
            {"name": "Color", "value": "Brown"}
        )
        self.assertEqual(attr_obj.name, "Color")
        self.assertIsNotNone(value_obj)
        self.assertEqual(value_obj.value, "Brown")
        self.assertEqual(free_text, "")

    def test_existing_attribute_case_insensitive(self):
        call_command("load_taxonomy", source=FIXTURE_PATH)
        attr_obj, value_obj, free_text = self._resolve(
            {"name": "color", "value": "brown"}
        )
        self.assertEqual(attr_obj.name, "Color")
        self.assertIsNotNone(value_obj)
        self.assertEqual(value_obj.value, "Brown")

    def test_no_match_creates_free_text(self):
        call_command("load_taxonomy", source=FIXTURE_PATH)
        attr_obj, value_obj, free_text = self._resolve(
            {"name": "Color", "value": "Teal"}
        )
        self.assertEqual(attr_obj.name, "Color")
        self.assertIsNone(value_obj)
        self.assertEqual(free_text, "Teal")

    def test_unknown_attribute_creates_new(self):
        attr_obj, value_obj, free_text = self._resolve(
            {"name": "Weight", "value": "5kg"}
        )
        self.assertEqual(attr_obj.name, "Weight")
        self.assertIsNone(value_obj)
        self.assertEqual(free_text, "5kg")
        self.assertTrue(Attribute.objects.filter(name="Weight").exists())

    def test_empty_name_returns_none(self):
        attr_obj, value_obj, free_text = self._resolve(
            {"name": "", "value": "test"}
        )
        self.assertIsNone(attr_obj)

    def test_empty_value_stored_as_free_text(self):
        call_command("load_taxonomy", source=FIXTURE_PATH)
        attr_obj, value_obj, free_text = self._resolve(
            {"name": "Color", "value": ""}
        )
        self.assertEqual(attr_obj.name, "Color")
        self.assertIsNone(value_obj)
        self.assertEqual(free_text, "")


class SaveClassificationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH)

    def _make_product(self, **kwargs):
        defaults = {
            "external_id": "test-123",
            "title": "Leather Sofa",
            "description": "A comfortable brown leather sofa",
        }
        defaults.update(kwargs)
        return Product.objects.create(**defaults)

    def test_classification_row_created(self):
        product = self._make_product()
        ai_resp = _ai_response()
        result = save_classification(product, ai_resp)
        self.assertIsNotNone(result.id)
        self.assertEqual(result.category.id, 15)
        self.assertAlmostEqual(result.confidence, 85.0)
        self.assertEqual(result.status, Classification.Status.APPROVED)

    def test_classification_source_defaults_to_ai(self):
        product = self._make_product()
        result = save_classification(product, _ai_response())
        self.assertEqual(result.source, Classification.Source.AI)

    def test_classification_source_rule(self):
        product = self._make_product()
        result = save_classification(
            product, _ai_response(), source=Classification.Source.RULE
        )
        self.assertEqual(result.source, Classification.Source.RULE)

    def test_classification_alternatives_saved(self):
        product = self._make_product()
        ai_resp = _ai_response()
        result = save_classification(product, ai_resp)
        self.assertEqual(len(result.alternatives), 1)
        self.assertEqual(result.alternatives[0]["category_id"], 19)

    def test_attributes_resolved_to_values(self):
        product = self._make_product()
        ai_resp = _ai_response()
        save_classification(product, ai_resp)
        attrs = ClassificationAttribute.objects.filter(classification__product=product)
        self.assertEqual(attrs.count(), 2)
        color_attr = attrs.get(attribute__name="Color")
        self.assertIsNotNone(color_attr.value)
        self.assertEqual(color_attr.value.value, "Brown")
        self.assertEqual(color_attr.free_text_value, "")

    def test_free_text_fallback(self):
        product = self._make_product()
        ai_resp = _ai_response(attributes=[{"name": "Color", "value": "Teal"}])
        save_classification(product, ai_resp)
        attr = ClassificationAttribute.objects.get(
            classification__product=product, attribute__name="Color"
        )
        self.assertIsNone(attr.value)
        self.assertEqual(attr.free_text_value, "Teal")

    @override_settings(CLASSIFICATION_CONFIDENCE_THRESHOLD=70)
    def test_above_threshold_auto_approves(self):
        product = self._make_product()
        result = save_classification(product, _ai_response())
        product.refresh_from_db()
        self.assertEqual(product.status, "done")
        self.assertEqual(result.status, Classification.Status.APPROVED)
        self.assertIsNone(result.reviewed_at)

    @override_settings(CLASSIFICATION_CONFIDENCE_THRESHOLD=70)
    def test_below_threshold_sets_needs_review(self):
        product = self._make_product()
        result = save_classification(product, _ai_response(confidence=50.0))
        product.refresh_from_db()
        self.assertEqual(product.status, "needs_review")
        self.assertEqual(result.status, Classification.Status.NEEDS_REVIEW)

    @override_settings(CLASSIFICATION_CONFIDENCE_THRESHOLD=70)
    def test_exactly_at_threshold_auto_approves(self):
        product = self._make_product()
        result = save_classification(product, _ai_response(confidence=70.0))
        product.refresh_from_db()
        self.assertEqual(product.status, "done")
        self.assertEqual(result.status, Classification.Status.APPROVED)

    def test_idempotent_on_rerun(self):
        product = self._make_product()
        save_classification(product, _ai_response())
        save_classification(product, _ai_response(confidence=90.0))
        self.assertEqual(Classification.objects.filter(product=product).count(), 1)
        c = Classification.objects.get(product=product)
        self.assertAlmostEqual(c.confidence, 90.0)

    def test_rollback_on_failure(self):
        product = self._make_product()
        ai_resp = _ai_response(attributes=[{"name": "Color", "value": "Brown"}])
        from unittest.mock import patch

        with patch(
            "classification.services.persistence.ClassificationAttribute"
            ".objects.create",
            side_effect=RuntimeError("DB error"),
        ):
            with self.assertRaises(RuntimeError):
                save_classification(product, ai_resp)
        self.assertFalse(Classification.objects.filter(product=product).exists())

    def test_missing_category_raises(self):
        product = self._make_product()
        with self.assertRaises(Category.DoesNotExist):
            save_classification(product, _ai_response(category_id=99999))
        self.assertFalse(Classification.objects.filter(product=product).exists())
