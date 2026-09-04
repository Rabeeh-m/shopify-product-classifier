import types
from unittest.mock import patch

from django.test import TestCase

from classification.services.rules import (
    FUZZY_MATCH_THRESHOLD,
    FUZZY_SKIP,
    FUZZY_WIN_MARGIN,
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
        types.SimpleNamespace(
            id=5, name="Office Chairs", full_path="Office > Office Chairs"
        ),
        types.SimpleNamespace(id=6, name="Chairs", full_path="Dining > Chairs"),
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


class FuzzyMatchTest(TestCase):
    """Fuzzy matching must be forgiving enough to catch typos/plurals but
    strict enough to avoid wrong-category risk."""

    def _patch_taxonomy(self):
        return patch(
            "taxonomy.services.cache.get_all_categories",
            return_value=_fake_categories(),
        )

    @patch.dict(
        VENDOR_CATEGORY_MAP,
        {"office chairs": "Office Chairs", "chair": "Chairs"},
        clear=True,
    )
    def test_typo_fuzzy_matches_to_rule(self):
        # "office chaire" (typo) is clearly closest to "office chairs" and the
        # fake taxonomy has an "Office Chairs" leaf → resolved as a rule, not
        # sent to AI.
        p = _product(product_type="office chaire")
        with self._patch_taxonomy():
            result = try_rule_classification(p)
        self.assertEqual(result["chosen_category_id"], 5)
        self.assertEqual(result["confidence"], VENDOR_RULE_CONFIDENCE)
        self.assertIn("[rules]", result["reasoning"])
        self.assertIn("fuzzy", result["reasoning"])

    @patch.dict(
        VENDOR_CATEGORY_MAP,
        {"office chairs": "Office Chairs", "chair": "Chairs"},
        clear=True,
    )
    def test_exact_match_still_beats_fuzzy(self):
        p = _product(product_type="office chairs")
        with self._patch_taxonomy():
            result = try_rule_classification(p)
        self.assertEqual(result["chosen_category_id"], 5)
        self.assertIn("exact", result["reasoning"])

    @patch.dict(
        VENDOR_CATEGORY_MAP,
        {"sectional sofas": "Sectional Sofas", "sofa": "Sofas"},
        clear=True,
    )
    def test_ambiguous_value_does_not_guess(self):
        # "sofa and chairs" has no exact hit and its best fuzzy matches ("sofa",
        # "sectional sofas") are close together → must NOT be guessed; fall to AI.
        p = _product(product_type="sofa and chairs")
        with self._patch_taxonomy():
            result = try_rule_classification(p)
        self.assertIsNone(result)

    @patch.dict(VENDOR_CATEGORY_MAP, {"sofa sectionals": "Sectional Sofas"})
    def test_skip_list_entries_are_never_fuzzy_matched(self):
        for ambiguous in FUZZY_SKIP:
            p = _product(product_type=ambiguous)
            with self._patch_taxonomy():
                self.assertIsNone(try_rule_classification(p))

    def test_threshold_and_margin_are_sanely_configured(self):
        # These knobs are what keep wrong-category risk low. Guard against
        # accidental weakening.
        self.assertGreaterEqual(FUZZY_MATCH_THRESHOLD, 80)
        self.assertGreaterEqual(FUZZY_WIN_MARGIN, 5)
