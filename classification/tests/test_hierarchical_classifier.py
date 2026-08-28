import json
import os
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from classification.services.classifier import classify_product
from products.models import Product
from taxonomy.models import Category

FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..",
    "taxonomy",
    "fixtures",
    "shopify",
)
CATEGORIES = os.path.join(FIXTURES, "sample_categories.json")
ATTRIBUTES = os.path.join(FIXTURES, "sample_attributes.json")


class HierarchicalClassifierTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command(
            "load_shopify_taxonomy",
            categories=CATEGORIES,
            attributes=ATTRIBUTES,
        )

    def _product(self):
        return Product.objects.create(
            external_id="x1",
            title="Brown Leather Sectional Sofa",
            description="A comfortable brown leather sectional sofa",
            brand="Acme",
        )

    def _smart_step_mock(self, target_name):
        """Return a call_ai side_effect that descends toward `target_name`."""

        def fake_call(prompt, **kwargs):
            # Find candidate ids/names in the prompt; pick the line whose name
            # is the target (or is an ancestor prefix); otherwise the last.
            import re

            names = re.findall(r"id: (\d+) \| (.*?)(?: \(leaf\))?\n", prompt)
            if not names:
                raise AssertionError("No candidates in prompt")
            # pick the deepest category whose name is a prefix-part of target
            chosen = None
            for cid, name in names:
                if target_name.lower() in name.lower():
                    chosen = cid
                    break
            if chosen is None:
                chosen = names[-1][0]
            return json.dumps(
                {
                    "chosen_category_id": int(chosen),
                    "confidence": 90.0,
                    "reasoning": "matches product",
                }
            )

        return fake_call

    @patch("classification.services.classifier.call_ai")
    def test_descends_to_leaf_and_constrains_attributes(self, mock_call_ai):
        product = self._product()
        target_leaf = Category.objects.get(name="Sectional Sofas")
        path_names = iter(["Furniture", "Living Room", "Sofas", "Sectional Sofas"])

        def fake_call(prompt, **kwargs):
            if "Allowed Attributes" in prompt:
                return json.dumps(
                    {
                        "attributes": [
                            {"name": "Color", "value": "Brown"},
                            {"name": "Totally Invalid", "value": "x"},
                        ]
                    }
                )
            expected = next(path_names)
            import re

            names = re.findall(r"id: (\d+) \| (.*)", prompt)
            for cid, name in names:
                if expected.lower() in name.lower():
                    return json.dumps(
                        {
                            "chosen_category_id": int(cid),
                            "confidence": 90.0,
                            "reasoning": "it is a sofa",
                        }
                    )
            return json.dumps(
                {
                    "chosen_category_id": int(names[0][0]),
                    "confidence": 50.0,
                    "reasoning": "fallback",
                }
            )

        mock_call_ai.side_effect = fake_call
        result = classify_product(product)

        self.assertEqual(result["chosen_category_id"], target_leaf.id)
        # Only Color is allowed for Sectional Sofas (plus it has no other attrs).
        self.assertEqual(
            [a["name"] for a in result["attributes"]], ["Color"]
        )
        self.assertEqual(result["attributes"][0]["value"], "Brown")
        # 90 minus the 5pt no-image penalty (test product has no image).
        self.assertEqual(result["confidence"], 85.0)

    @patch("classification.services.classifier.call_ai")
    def test_extra_attribute_call_happens(self, mock_call_ai):
        product = self._product()
        calls = []
        leaf = Category.objects.get(name="Memory Foam Mattresses")
        path_names = iter(
            ["Furniture", "Beds & Accessories", "Mattresses", "Memory Foam Mattresses"]
        )

        def fake_call(prompt, **kwargs):
            calls.append(prompt)
            if "Allowed Attributes" in prompt:
                return json.dumps({"attributes": []})
            expected = next(path_names)
            import re

            names = re.findall(r"id: (\d+) \| (.*)", prompt)
            for cid, name in names:
                if expected.lower() in name.lower():
                    return json.dumps(
                        {
                            "chosen_category_id": int(cid),
                            "confidence": 88.0,
                            "reasoning": "matches",
                        }
                    )
            return json.dumps(
                {
                    "chosen_category_id": int(names[0][0]),
                    "confidence": 40.0,
                    "reasoning": "fallback",
                }
            )

        mock_call_ai.side_effect = fake_call
        result = classify_product(product)

        self.assertEqual(result["chosen_category_id"], leaf.id)
        self.assertEqual(result["attributes"], [])
        # At least one attribute-extraction call should have been made.
        self.assertTrue(any("Allowed Attributes" in p for p in calls))
