import json
import types
from unittest.mock import patch

from django.test import TestCase

from classification.exceptions import (
    AIClientError,
    AITimeoutError,
    ClassificationParseError,
)
from classification.services.classifier import (
    _build_prompt,
    _parse_and_validate,
    adjust_confidence,
    classify_product,
)

_FAKE_CATEGORIES = [
    types.SimpleNamespace(id=10, name="Sofas", full_path="Furniture > Sofas"),
    types.SimpleNamespace(id=20, name="Chairs", full_path="Furniture > Chairs"),
    types.SimpleNamespace(id=30, name="Tables", full_path="Furniture > Tables"),
]

_FAKE_PRODUCT = types.SimpleNamespace(
    title="Leather Sofa",
    description="A comfortable brown leather sofa",
    brand="Acme",
    product_type="Furniture",
    images=types.SimpleNamespace(
        first=lambda: types.SimpleNamespace(url="https://example.com/sofa.jpg")
    ),
)


def _good_response():
    return json.dumps(
        {
            "chosen_category_id": 10,
            "alternatives": [
                {"category_id": 20, "confidence": 25.0},
                {"category_id": 30, "confidence": 10.0},
            ],
            "attributes": [
                {"name": "Color", "value": "Brown"},
                {"name": "Material", "value": "Leather"},
            ],
            "confidence": 82.5,
            "reasoning": (
                "Product is explicitly a leather sofa, matching "
                "the Sofas category."
            ),
        }
    )


class BuildPromptTest(TestCase):
    def test_prompt_contains_product_fields(self):
        prompt = _build_prompt(_FAKE_PRODUCT, _FAKE_CATEGORIES)
        self.assertIn("Leather Sofa", prompt)
        self.assertIn("comfortable brown leather sofa", prompt)
        self.assertIn("Acme", prompt)
        self.assertIn("Furniture", prompt)

    def test_prompt_contains_taxonomy_ids(self):
        prompt = _build_prompt(_FAKE_PRODUCT, _FAKE_CATEGORIES)
        self.assertIn("id: 10", prompt)
        self.assertIn("id: 20", prompt)
        self.assertIn("id: 30", prompt)

    def test_prompt_contains_category_names(self):
        prompt = _build_prompt(_FAKE_PRODUCT, _FAKE_CATEGORIES)
        self.assertIn("Sofas", prompt)
        self.assertIn("Chairs", prompt)
        self.assertIn("Tables", prompt)

    def test_prompt_contains_image_url(self):
        prompt = _build_prompt(_FAKE_PRODUCT, _FAKE_CATEGORIES)
        self.assertIn("https://example.com/sofa.jpg", prompt)

    def test_prompt_handles_no_image(self):
        product = types.SimpleNamespace(
            title="Test",
            description="",
            brand="",
            product_type="",
            images=types.SimpleNamespace(first=lambda: None),
        )
        prompt = _build_prompt(product, _FAKE_CATEGORIES)
        self.assertNotIn("image URL", prompt)

    def test_prompt_handles_minimal_product(self):
        product = types.SimpleNamespace(
            title="Widget",
            description="",
            brand="",
            product_type="",
            images=types.SimpleNamespace(first=lambda: None),
        )
        prompt = _build_prompt(product, _FAKE_CATEGORIES)
        self.assertIn("Widget", prompt)
        self.assertIn("(none)", prompt)


class ParseAndValidateTest(TestCase):
    def test_valid_response(self):
        result = _parse_and_validate(_good_response(), {10, 20, 30})
        self.assertEqual(result["chosen_category_id"], 10)
        self.assertEqual(result["confidence"], 82.5)
        self.assertEqual(len(result["alternatives"]), 2)
        self.assertEqual(len(result["attributes"]), 2)
        self.assertIn("leather sofa", result["reasoning"].lower())

    def test_invalid_json_raises(self):
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate("not json at all {{{", {10, 20})
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_non_object_json_raises(self):
        with self.assertRaises(ClassificationParseError):
            _parse_and_validate('["not", "an", "object"]', {10, 20})

    def test_missing_chosen_category_id_raises(self):
        resp = json.dumps({"confidence": 80, "reasoning": "test"})
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate(resp, {10, 20})
        self.assertIn("chosen_category_id", str(ctx.exception))

    def test_chosen_id_not_in_taxonomy_raises(self):
        resp = json.dumps(
            {
                "chosen_category_id": 999,
                "confidence": 80,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate(resp, {10, 20, 30})
        self.assertIn("999", str(ctx.exception))
        self.assertIn("not in the taxonomy", str(ctx.exception))

    def test_missing_confidence_raises(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError):
            _parse_and_validate(resp, {10})

    def test_confidence_out_of_range_raises(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "confidence": 150,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate(resp, {10})
        self.assertIn("out of range", str(ctx.exception))

    def test_negative_confidence_raises(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "confidence": -5,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError):
            _parse_and_validate(resp, {10})

    def test_alternatives_must_be_list(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "confidence": 80,
                "alternatives": "not a list",
                "attributes": [],
                "reasoning": "test",
            }
        )
        # Non-list alternatives are coerced to empty, not an error.
        result = _parse_and_validate(resp, {10})
        self.assertEqual(result["alternatives"], [])

    def test_attributes_must_be_list(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "confidence": 80,
                "alternatives": [],
                "attributes": "not a list",
                "reasoning": "test",
            }
        )
        result = _parse_and_validate(resp, {10})
        self.assertEqual(result["attributes"], [])

    def test_raw_response_preserved_on_error(self):
        raw = "garbage output"
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate(raw, {10})
        self.assertEqual(ctx.exception.raw_response, raw)


def _patched_taxonomy():
    return patch(
        "taxonomy.services.cache.get_all_categories",
        return_value=_FAKE_CATEGORIES,
    )


@patch("classification.services.classifier.call_ai")
class ClassifyProductTest(TestCase):
    def test_successful_classification(self, mock_call_ai):
        mock_call_ai.return_value = _good_response()
        with _patched_taxonomy():
            result = classify_product(_FAKE_PRODUCT)
        self.assertEqual(result["chosen_category_id"], 10)
        self.assertEqual(result["confidence"], 82.5)
        mock_call_ai.assert_called_once()

    def test_ai_returns_invalid_json(self, mock_call_ai):
        mock_call_ai.return_value = "this is not json"
        with _patched_taxonomy(), self.assertRaises(ClassificationParseError):
            classify_product(_FAKE_PRODUCT)

    def test_ai_chooses_invalid_category(self, mock_call_ai):
        resp = json.dumps(
            {
                "chosen_category_id": 999,
                "confidence": 80,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        mock_call_ai.return_value = resp
        with _patched_taxonomy(), self.assertRaises(ClassificationParseError):
            classify_product(_FAKE_PRODUCT)

    def test_api_error_propagates(self, mock_call_ai):
        mock_call_ai.side_effect = AIClientError("API down")
        with _patched_taxonomy(), self.assertRaises(AIClientError):
            classify_product(_FAKE_PRODUCT)

    def test_timeout_propagates(self, mock_call_ai):
        mock_call_ai.side_effect = AITimeoutError("timed out")
        with _patched_taxonomy(), self.assertRaises(AITimeoutError):
            classify_product(_FAKE_PRODUCT)

    def test_alternatives_and_attributes_parsed(self, mock_call_ai):
        mock_call_ai.return_value = _good_response()
        with _patched_taxonomy():
            result = classify_product(_FAKE_PRODUCT)
        self.assertEqual(result["alternatives"][0]["category_id"], 20)
        self.assertEqual(result["attributes"][0]["name"], "Color")
        self.assertEqual(result["attributes"][0]["value"], "Brown")


class AdjustConfidenceTest(TestCase):
    def _product(self, description="", image_url=None):
        images = [types.SimpleNamespace(url=image_url)] if image_url else []
        return types.SimpleNamespace(
            title="Test",
            description=description,
            images=types.SimpleNamespace(
                first=lambda: images[0] if images else None
            ),
        )

    def test_full_data_keeps_confidence(self):
        p = self._product(description="desc", image_url="http://x/img.jpg")
        self.assertEqual(adjust_confidence(p, 85.0), 85.0)

    def test_title_only_caps_at_50(self):
        p = self._product()
        self.assertEqual(adjust_confidence(p, 95.0), 50.0)

    def test_no_description_caps_at_65(self):
        p = self._product(image_url="http://x/img.jpg")
        self.assertEqual(adjust_confidence(p, 90.0), 65.0)

    def test_no_image_subtracts_five(self):
        p = self._product(description="desc")
        self.assertEqual(adjust_confidence(p, 80.0), 75.0)

    def test_no_image_floors_at_30(self):
        p = self._product(description="desc")
        self.assertEqual(adjust_confidence(p, 25.0), 30.0)
