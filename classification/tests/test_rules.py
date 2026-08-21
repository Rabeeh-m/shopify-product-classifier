import types
from unittest.mock import patch

from django.test import TestCase

from classification.services.rules import (
    VENDOR_CATEGORY_MAP,
    VENDOR_RULE_CONFIDENCE,
    _normalize,
    get_vendor_sub_category,
    try_rule_classification,
)


def _fake_categories():
    return [
        types.SimpleNamespace(id=1, name="Sofas", full_path="Living Room > Sofas"),
        types.SimpleNamespace(
            id=2, name="Sectional Sofas", full_path="Living Room > Sectional Sofas"
        ),
        types.SimpleNamespace(id=3, name="Bar Stools", full_path="Dining > Bar Stools"),
        types.SimpleNamespace(
            id=4, name="Throw Pillows", full_path="Decor > Throw Pillows"
        ),
    ]


def _product(**kwargs):
    defaults = {
        "id": 42,
        "title": "Empress Sofa",
        "description": "A leather sofa",
        "brand": "Empress",
        "product_type": "",
        "raw_data": {},
        "images": types.SimpleNamespace(first=lambda: None),
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


class NormalizeTest(TestCase):
    def test_lowercases_and_collapses_whitespace(self):
        self.assertEqual(
            _normalize("  Bar   and Counter Stools "), "bar and counter stools"
        )

    def test_none_and_empty(self):
        self.assertEqual(_normalize(None), "")
        self.assertEqual(_normalize(""), "")


class GetVendorSubCategoryTest(TestCase):
    def test_prefers_product_sub_category(self):
        p = _product(raw_data={"product_sub_category": "Sofa Sectionals"})
        self.assertEqual(get_vendor_sub_category(p), "Sofa Sectionals")

    def test_falls_back_to_product_category(self):
        p = _product(raw_data={"product_category": "Vanities"})
        self.assertEqual(get_vendor_sub_category(p), "Vanities")

    def test_falls_back_to_product_type(self):
        p = _product(product_type="Office Chairs")
        self.assertEqual(get_vendor_sub_category(p), "Office Chairs")

    def test_empty_everything(self):
        self.assertEqual(get_vendor_sub_category(_product()), "")


class TryRuleClassificationTest(TestCase):
    def _patch_taxonomy(self):
        return patch(
            "taxonomy.services.cache.get_all_categories",
            return_value=_fake_categories(),
        )

    @patch.dict(VENDOR_CATEGORY_MAP, {"sofa sectionals": "Sectional Sofas"}, clear=True)
    def test_match_returns_full_result(self):
        p = _product(
            raw_data={
                "product_sub_category": "Sofa Sectionals",
                "product_color": "Charcoal",
                "materials": "Velvet",
            },
            images=types.SimpleNamespace(
                first=lambda: types.SimpleNamespace(url="http://x/img.jpg")
            ),
        )
        with self._patch_taxonomy():
            result = try_rule_classification(p)

        self.assertEqual(result["chosen_category_id"], 2)
        self.assertEqual(result["confidence"], VENDOR_RULE_CONFIDENCE)
        self.assertEqual(result["attributes"], [
            {"name": "Color", "value": "Charcoal"},
            {"name": "Material", "value": "Velvet"},
        ])
        self.assertIn("[rules]", result["reasoning"])

    @patch.dict(
        VENDOR_CATEGORY_MAP,
        {"bar and counter stools": "Bar Stools", "unknown thing": "No Such Leaf"},
        clear=True,
    )
    def test_no_map_hit_returns_none(self):
        with self._patch_taxonomy():
            self.assertIsNone(try_rule_classification(_product()))

    @patch.dict(VENDOR_CATEGORY_MAP, {"unknown thing": "No Such Leaf"}, clear=True)
    def test_mapped_but_missing_leaf_falls_back_to_ai(self):
        # Missing taxonomy leaf must NOT fail the product — the AI pass
        # gets a chance instead.
        with self._patch_taxonomy():
            self.assertIsNone(
                try_rule_classification(_product(product_type="Unknown Thing"))
            )

    @patch.dict(VENDOR_CATEGORY_MAP, {"pillow": "Throw Pillows"}, clear=True)
    def test_case_insensitive_hit(self):
        p = _product(product_type="PILLOW")
        with self._patch_taxonomy():
            result = try_rule_classification(p)
        self.assertEqual(result["chosen_category_id"], 4)

    def test_real_map_has_no_conflicting_targets(self):
        # Every mapped value must be a unique leaf name.
        values = list(VENDOR_CATEGORY_MAP.values())
        self.assertEqual(len(values), len(set(values)))
