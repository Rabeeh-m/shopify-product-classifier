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
    _build_attributes_prompt,
    _build_step_prompt,
    _parse_attributes,
    _parse_step,
    adjust_confidence,
    classify_product,
)

_FAKE_CATEGORIES = [
    types.SimpleNamespace(
        id=10, name="Sofas", full_path="Furniture > Sofas", children=[]
    ),
    types.SimpleNamespace(
        id=20, name="Chairs", full_path="Furniture > Chairs", children=[]
    ),
    types.SimpleNamespace(
        id=30, name="Tables", full_path="Furniture > Tables", children=[]
    ),
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


class BuildStepPromptTest(TestCase):
    def test_prompt_contains_product_fields(self):
        prompt = _build_step_prompt(_FAKE_PRODUCT, [], _FAKE_CATEGORIES)
        self.assertIn("Leather Sofa", prompt)
        self.assertIn("Acme", prompt)
        self.assertIn("top level", prompt)

    def test_prompt_contains_path(self):
        prompt = _build_step_prompt(
            _FAKE_PRODUCT, ["Furniture", "Sofas"], _FAKE_CATEGORIES
        )
        self.assertIn("Furniture > Sofas", prompt)

    def test_prompt_lists_candidate_ids(self):
        prompt = _build_step_prompt(_FAKE_PRODUCT, [], _FAKE_CATEGORIES)
        self.assertIn("id: 10", prompt)
        self.assertIn("id: 20", prompt)
        self.assertIn("id: 30", prompt)

    def test_prompt_contains_image_url(self):
        prompt = _build_step_prompt(_FAKE_PRODUCT, [], _FAKE_CATEGORIES)
        self.assertIn("https://example.com/sofa.jpg", prompt)

    def test_prompt_handles_no_image_and_no_text(self):
        product = types.SimpleNamespace(
            title="Widget",
            description="",
            brand="",
            product_type="",
            images=types.SimpleNamespace(first=lambda: None),
        )
        prompt = _build_step_prompt(product, [], _FAKE_CATEGORIES)
        self.assertNotIn("image URL", prompt)
        self.assertIn("(none)", prompt)


class BuildAttributesPromptTest(TestCase):
    def test_prompt_lists_category_and_allowed_attrs(self):
        category = types.SimpleNamespace(
            name="Sofas", full_path="Furniture > Sofas"
        )
        attrs = [("Color", ["Red", "Brown"]), ("Material", ["Leather", "Cotton"])]
        prompt = _build_attributes_prompt(_FAKE_PRODUCT, category, attrs)
        self.assertIn("Furniture > Sofas", prompt)
        self.assertIn("Color", prompt)
        self.assertIn("Brown", prompt)
        self.assertIn("Material", prompt)


class ParseStepTest(TestCase):
    def _step(self, **overrides):
        data = {
            "chosen_category_id": 10,
            "confidence": 82.5,
            "reasoning": "Leather sofa.",
        }
        data.update(overrides)
        return json.dumps(data)

    def test_valid_step(self):
        result = _parse_step(self._step())
        self.assertEqual(result["chosen_category_id"], 10)
        self.assertEqual(result["confidence"], 82.5)
        self.assertEqual(result["reasoning"], "Leather sofa.")

    def test_invalid_json_raises(self):
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_step("not json")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_non_object_raises(self):
        with self.assertRaises(ClassificationParseError):
            _parse_step('[1, 2, 3]')

    def test_missing_id_raises(self):
        with self.assertRaises(ClassificationParseError):
            _parse_step(self._step(chosen_category_id=None))

    def test_missing_confidence_raises(self):
        with self.assertRaises(ClassificationParseError):
            _parse_step(json.dumps({"chosen_category_id": 10, "reasoning": "x"}))

    def test_confidence_out_of_range_raises(self):
        with self.assertRaises(ClassificationParseError):
            _parse_step(self._step(confidence=150))

    def test_alternatives_coerced_to_list(self):
        result = _parse_step(self._step(alternatives="not a list"))
        self.assertEqual(result["alternatives"], [])


class ParseAttributesTest(TestCase):
    def test_valid_attributes(self):
        resp = json.dumps(
            {"attributes": [{"name": "Color", "value": "Brown"}]}
        )
        result = _parse_attributes(resp, {"Color"})
        self.assertEqual(result["attributes"], [{"name": "Color", "value": "Brown"}])

    def test_invalid_json_raises(self):
        with self.assertRaises(ClassificationParseError):
            _parse_attributes("nope", {"Color"})

    def test_non_list_attributes_coerced(self):
        result = _parse_attributes(json.dumps({"attributes": "x"}), {"Color"})
        self.assertEqual(result["attributes"], [])

    def test_empty_name_items_skipped(self):
        resp = json.dumps(
            {
                "attributes": [
                    {"name": "", "value": "x"},
                    {"name": "Color", "value": "Red"},
                ]
            }
        )
        result = _parse_attributes(resp, {"Color"})
        self.assertEqual(result["attributes"], [{"name": "Color", "value": "Red"}])


def _patched_hierarchy(categories):
    """Mock the hierarchy so classify_product picks from `categories` directly."""
    patch_targets = [
        patch(
            "classification.services.classifier.get_root_categories",
            return_value=categories,
        ),
        patch(
            "classification.services.classifier.get_children",
            side_effect=lambda c: [],
        ),
    ]
    return patch_targets


class ClassifyProductTest(TestCase):
    def _run_classify(self, mock_call_ai, category, step_json=None, attrs_json=None):
        step_json = step_json or {
            "chosen_category_id": category.id,
            "confidence": 82.5,
            "reasoning": "fits.",
        }
        attrs_json = attrs_json or {
            "attributes": [
                {"name": "Color", "value": "Brown"},
                {"name": "Material", "value": "Leather"},
            ]
        }
        mock_call_ai.side_effect = [json.dumps(step_json), json.dumps(attrs_json)]
        with (
            patch(
                "classification.services.classifier.get_root_categories",
                return_value=[category],
            ),
            patch(
                "classification.services.classifier.get_children",
                return_value=[],
            ),
            patch(
                "classification.services.classifier._attribute_options",
                return_value=[
                    ("Color", ["Brown", "Red"]),
                    ("Material", ["Leather", "Cotton"]),
                ],
            ),
        ):
            return classify_product(_FAKE_PRODUCT)

    @patch("classification.services.classifier.call_ai")
    def test_successful_classification(self, mock_call_ai):
        category = types.SimpleNamespace(
            id=10, name="Sofas", full_path="Furniture > Sofas"
        )
        result = self._run_classify(mock_call_ai, category)
        self.assertEqual(result["chosen_category_id"], 10)
        self.assertEqual(mock_call_ai.call_count, 2)
        # confidence 82.5 with full product data is unchanged
        self.assertEqual(result["confidence"], 82.5)

    @patch("classification.services.classifier.call_ai")
    def test_attributes_are_constrained_to_allowed(self, mock_call_ai):
        category = types.SimpleNamespace(
            id=10, name="Sofas", full_path="Furniture > Sofas"
        )
        attrs_json = {
            "attributes": [
                {"name": "Color", "value": "Brown"},
                {"name": "Disallowed", "value": "X"},
            ]
        }
        result = self._run_classify(mock_call_ai, category, attrs_json=attrs_json)
        names = [a["name"] for a in result["attributes"]]
        self.assertEqual(names, ["Color"])
        self.assertNotIn("Disallowed", names)

    @patch("classification.services.classifier.call_ai")
    def test_invalid_step_json_raises(self, mock_call_ai):
        mock_call_ai.side_effect = ["not json", ""]
        with (
            patch(
                "classification.services.classifier.get_root_categories",
                return_value=[types.SimpleNamespace(id=10, name="Sofas")],
            ),
            patch(
                "classification.services.classifier.get_children",
                return_value=[],
            ),
            self.assertRaises(ClassificationParseError),
        ):
            classify_product(_FAKE_PRODUCT)

    @patch("classification.services.classifier.call_ai")
    def test_ai_error_propagates(self, mock_call_ai):
        mock_call_ai.side_effect = AIClientError("API down")
        with (
            patch(
                "classification.services.classifier.get_root_categories",
                return_value=[types.SimpleNamespace(id=10, name="Sofas")],
            ),
            patch(
                "classification.services.classifier.get_children",
                return_value=[],
            ),
            self.assertRaises(AIClientError),
        ):
            classify_product(_FAKE_PRODUCT)

    @patch("classification.services.classifier.call_ai")
    def test_timeout_propagates(self, mock_call_ai):
        mock_call_ai.side_effect = AITimeoutError("timed out")
        with (
            patch(
                "classification.services.classifier.get_root_categories",
                return_value=[types.SimpleNamespace(id=10, name="Sofas")],
            ),
            patch(
                "classification.services.classifier.get_children",
                return_value=[],
            ),
            self.assertRaises(AITimeoutError),
        ):
            classify_product(_FAKE_PRODUCT)


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
