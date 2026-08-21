import os

from django.core.management import call_command
from django.test import TestCase, override_settings

from classification.services.rule_classifier import try_rule_classification
from classification.tasks import _run_pipeline
from products.models import Product
from taxonomy.models import Category

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..",
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)


class RuleClassifierTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)
        cls.sectional = Category.objects.get(name="Sectional Sofas")
        cls.armchairs = Category.objects.get(name="Armchairs")
        cls.loveseats = Category.objects.get(name="Loveseats")
        cls.sofas = Category.objects.get(name="Sofas")
        cls.dining_chairs = Category.objects.get(name="Dining Chairs")

    def _product(self, **kwargs):
        defaults = {
            "external_id": "rule-test-1",
            "title": "Test Product",
            "product_type": "",
            "raw_data": {},
        }
        defaults.update(kwargs)
        return Product.objects.create(**defaults)

    def test_vendor_direct_mapping_sectionals(self):
        product = self._product(
            external_id="sec-1",
            title="Large U-Shape Sectional",
            product_type="Sofa Sectionals",
            raw_data={
                "product_sub_category": "Sofa Sectionals",
                "product_color": "Gray",
                "materials": "Polyester",
            },
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], self.sectional.id)
        self.assertEqual(result["attributes"][0]["value"], "Gray")
        self.assertIn("[rules]", result["reasoning"])

    def test_vendor_title_rule_armchair(self):
        product = self._product(
            external_id="arm-1",
            title="Empress Upholstered Fabric Armchair by Modway",
            product_type="Sofas and Armchairs",
            raw_data={"product_sub_category": "Sofas and Armchairs"},
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], self.armchairs.id)

    def test_vendor_title_rule_sofa(self):
        product = self._product(
            external_id="sofa-1",
            title="Empress Bonded Leather Sofa by Modway",
            product_type="Sofas and Armchairs",
            raw_data={"product_sub_category": "Sofas and Armchairs"},
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], self.sofas.id)

    def test_vendor_title_rule_loveseat_beats_generic_sofa(self):
        product = self._product(
            external_id="love-1",
            title="Empress Bonded Leather Loveseat by Modway",
            product_type="Sofas and Armchairs",
            raw_data={"product_sub_category": "Sofas and Armchairs"},
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], self.loveseats.id)

    def test_vendor_direct_mapping_dining_chairs(self):
        product = self._product(
            external_id="dc-1",
            title="Classic Dining Chair",
            product_type="Dining Chairs",
            raw_data={"product_sub_category": "Dining Chairs"},
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], self.dining_chairs.id)

    def test_vendor_direct_mapping_vanities(self):
        vanities = Category.objects.get(name="Vanities")
        product = self._product(
            external_id="van-1",
            title="Aria 48\" White Vanity With Marble Top",
            product_type="Vanities",
            raw_data={
                "product_sub_category": "Vanities",
                "product_color": "White",
                "materials": "Marble",
            },
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], vanities.id)
        self.assertEqual(result["attributes"][0]["value"], "White")
        self.assertEqual(result["attributes"][1]["value"], "Marble")

    def test_decor_trash_bin_maps_to_waste_baskets(self):
        waste_baskets = Category.objects.get(name="Waste Baskets")
        product = self._product(
            external_id="dec-1",
            title="Lava Trash Bin by Modway",
            product_type="Decor",
            raw_data={"product_sub_category": "Decor"},
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], waste_baskets.id)

    def test_decor_tv_stand_maps_to_tv_stands(self):
        tv_stands = Category.objects.get(name="TV Stands")
        product = self._product(
            external_id="dec-2",
            title="Transmit 55\" TV Stand by Modway",
            product_type="Decor",
            raw_data={"product_sub_category": "Decor"},
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], tv_stands.id)

    def test_case_goods_nightstand_and_mirror(self):
        nightstands = Category.objects.get(name="Nightstands")
        mirrors = Category.objects.get(name="Mirrors")
        nightstand = self._product(
            external_id="cg-1",
            title="Dispatch Nightstand by Modway",
            product_type="Case Goods",
            raw_data={"product_sub_category": "Case Goods"},
        )
        mirror = self._product(
            external_id="cg-2",
            title="Glint Mirror by Modway",
            product_type="Case Goods",
            raw_data={"product_sub_category": "Case Goods"},
        )
        self.assertEqual(
            try_rule_classification(nightstand, [])["chosen_category_id"],
            nightstands.id,
        )
        self.assertEqual(
            try_rule_classification(mirror, [])["chosen_category_id"],
            mirrors.id,
        )

    def test_dining_sets_kitchen_cart_vs_default_set(self):
        carts = Category.objects.get(name="Kitchen Islands & Carts")
        dining_sets = Category.objects.get(name="Dining Sets")
        cart = self._product(
            external_id="ds-1",
            title="Culinary Kitchen Cart With Towel Bar by Modway",
            product_type="Dining Sets",
            raw_data={"product_sub_category": "Dining Sets"},
        )
        table_set = self._product(
            external_id="ds-2",
            title="Prosper 5 Piece Upholstered Velvet Dining Set by Modway",
            product_type="Dining Sets",
            raw_data={"product_sub_category": "Dining Sets"},
        )
        self.assertEqual(
            try_rule_classification(cart, [])["chosen_category_id"], carts.id
        )
        # No title-rule match falls back to the sub-category default.
        self.assertEqual(
            try_rule_classification(table_set, [])["chosen_category_id"],
            dining_sets.id,
        )

    def test_daybeds_swing_chair_vs_default(self):
        swings = Category.objects.get(name="Patio Swing Chairs")
        daybeds = Category.objects.get(name="Daybeds")
        swing = self._product(
            external_id="dl-1",
            title="Hide Outdoor Patio Swing Chair With Stand by Modway",
            product_type="Daybeds and Lounges",
            raw_data={"product_sub_category": "Daybeds and Lounges"},
        )
        lounge = self._product(
            external_id="dl-2",
            title="Encase Outdoor Patio Lounge Bed by Modway",
            product_type="Daybeds and Lounges",
            raw_data={"product_sub_category": "Daybeds and Lounges"},
        )
        self.assertEqual(
            try_rule_classification(swing, [])["chosen_category_id"], swings.id
        )
        self.assertEqual(
            try_rule_classification(lounge, [])["chosen_category_id"], daybeds.id
        )

    def test_lighting_subcategories_direct_mapping(self):
        ceiling = Category.objects.get(name="Ceiling Lights")
        table_lamp = Category.objects.get(name="Table Lamps")
        floor_lamp = Category.objects.get(name="Floor Lamps")
        for sub, expected in (
            ("Ceiling Lamps", ceiling),
            ("Table Lamps", table_lamp),
            ("Floor Lamps", floor_lamp),
        ):
            product = self._product(
                external_id=f"li-{sub[:4]}",
                title=f"Element Glass {sub} by Modway",
                product_type=sub,
                raw_data={"product_sub_category": sub},
            )
            result = try_rule_classification(product, [])
            self.assertIsNotNone(result)
            self.assertEqual(result["chosen_category_id"], expected.id)

    def test_bar_and_dining_stool_maps_to_bar_stools_not_dining_chairs(self):
        bar_stools = Category.objects.get(name="Bar Stools")
        product = self._product(
            external_id="bd-1",
            title="Maine Outdoor Patio Bar Stool by Modway",
            product_type="Bar and Dining",
            raw_data={"product_sub_category": "Bar and Dining"},
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNotNone(result)
        self.assertEqual(result["chosen_category_id"], bar_stools.id)

    def test_mixed_subcategory_direct_mappings(self):
        expected = {
            "Office Chairs": ("Ergonomic Mesh Swivel Office Chair", "Office Chairs"),
            "Benches and Stools": (
                "Valet Performance Velvet Bench",
                "Benches",
            ),
            "Pillow": (
                "Enhance 24\" Performance Velvet Throw Pillow",
                "Throw Pillows",
            ),
        }
        for sub, (title, category_name) in expected.items():
            product = self._product(
                external_id=f"mx-{category_name[:6]}",
                title=title,
                product_type=sub,
                raw_data={"product_sub_category": sub},
            )
            result = try_rule_classification(product, [])
            self.assertIsNotNone(result)
            self.assertEqual(
                result["chosen_category_id"],
                Category.objects.get(name=category_name).id,
            )

    def test_unknown_vendor_category_falls_through_to_keywords(self):
        from classification.services.candidate_finder import find_candidates

        product = self._product(
            external_id="kw-1",
            title="Gray Fabric Sectional Sofa With Reversible Chaise",
            description="Upholstered sectional with plush cushions",
            product_type="Import Specials",
        )
        candidates = find_candidates(product)
        result = try_rule_classification(product, candidates)
        self.assertIsNotNone(result)
        self.assertEqual(
            result["chosen_category_id"],
            candidates[0].category.id,
        )
        self.assertEqual(result["chosen_category_id"], self.sectional.id)

    def test_ambiguous_candidates_return_none(self):
        from classification.services.candidate_finder import CandidateResult

        product = self._product(
            external_id="amb-1",
            title="Chair",
            product_type="Unknown Vendor Category",
        )
        cat_a = Category.objects.get(name="Armchairs")
        cat_b = Category.objects.get(name="Accent Chairs")
        candidates = [
            CandidateResult(category=cat_a, score=6.5),
            CandidateResult(category=cat_b, score=6.0),
        ]
        result = try_rule_classification(product, candidates)
        self.assertIsNone(result)

    @override_settings(RULE_CLASSIFICATION_ENABLED=False)
    def test_disabled_rules_return_none(self):
        product = self._product(
            external_id="off-1",
            title="Sectional Sofa",
            product_type="Sofa Sectionals",
            raw_data={"product_sub_category": "Sofa Sectionals"},
        )
        result = try_rule_classification(product, candidates=[])
        self.assertIsNone(result)


class RulePipelineIntegrationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)

    def test_pipeline_uses_rules_without_ai(self):
        from unittest.mock import patch

        product = Product.objects.create(
            external_id="pipe-2",
            title="Empress Bonded Leather Sofa by Modway",
            product_type="Sofas and Armchairs",
            raw_data={
                "product_sub_category": "Sofas and Armchairs",
                "product_color": "White",
            },
        )

        with patch("classification.services.classifier.call_ai") as mock_ai:
            _run_pipeline(product)
            mock_ai.assert_not_called()

        product.refresh_from_db()
        self.assertEqual(product.status, "done")
        self.assertEqual(product.classification.status, "approved")
        self.assertEqual(product.classification.category.name, "Sofas")

    def test_pipeline_falls_back_to_ai_when_rules_miss(self):
        import json
        from unittest.mock import patch

        product = Product.objects.create(
            external_id="pipe-3",
            title="Mystery Gadget",
            description="An unclassifiable novelty item",
            product_type="Unknown",
        )
        sectional = Category.objects.get(name="Sectional Sofas")

        with patch(
            "classification.services.rule_classifier.try_rule_classification",
            return_value=None,
        ), patch("classification.services.classifier.call_ai") as mock_ai:
            mock_ai.return_value = json.dumps(
                {
                    "chosen_category_id": sectional.id,
                    "alternatives": [],
                    "attributes": [],
                    "confidence": 75.0,
                    "reasoning": "Best guess.",
                }
            )
            _run_pipeline(product)
            mock_ai.assert_called_once()

        product.refresh_from_db()
        self.assertEqual(product.classification.category_id, sectional.id)
