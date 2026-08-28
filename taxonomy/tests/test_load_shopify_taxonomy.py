import os

from django.core.management import call_command
from django.test import TestCase

from taxonomy.models import Attribute, AttributeValue, Category, CategoryAttribute

FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "fixtures", "shopify"
)
CATEGORIES = os.path.join(FIXTURES, "sample_categories.json")
ATTRIBUTES = os.path.join(FIXTURES, "sample_attributes.json")


class LoadShopifyTaxonomyTest(TestCase):
    def _load(self, dry_run=False):
        call_command(
            "load_shopify_taxonomy",
            categories=CATEGORIES,
            attributes=ATTRIBUTES,
            dry_run=dry_run,
        )

    def test_loads_categories_with_parents(self):
        self._load()
        self.assertEqual(Category.objects.count(), 7)
        sofas = Category.objects.get(name="Sofas")
        self.assertEqual(sofas.full_path, "Furniture > Living Room > Sofas")
        self.assertEqual(sofas.parent.name, "Living Room")
        self.assertEqual(sofas.parent.parent.name, "Furniture")
        self.assertEqual(
            sofas.shopify_category_id,
            "gid://shopify/TaxonomyCategory/fr-1-1",
        )
        sectional = Category.objects.get(name="Sectional Sofas")
        self.assertEqual(sectional.parent.name, "Sofas")

    def test_loads_attributes_and_values(self):
        self._load()
        color = Attribute.objects.get(name="Color")
        self.assertEqual(
            color.shopify_attribute_gid,
            "gid://shopify/TaxonomyAttribute/1",
        )
        values = set(color.values.values_list("value", flat=True))
        self.assertEqual(values, {"Red", "Blue", "Brown", "Black"})
        pattern = Attribute.objects.get(name="Pattern")
        self.assertIn("Striped", pattern.values.values_list("value", flat=True))

    def test_loads_category_attribute_links(self):
        self._load()
        sofas = Category.objects.get(name="Sofas")
        linked = set(
            Attribute.objects.filter(category_attributes__category=sofas).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(linked, {"Color", "Pattern"})
        mattr = Category.objects.get(name="Mattresses")
        mlinked = set(
            Attribute.objects.filter(category_attributes__category=mattr).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(mlinked, {"Pattern"})

    def test_leaf_category_has_no_children(self):
        self._load()
        sectional = Category.objects.get(name="Sectional Sofas")
        self.assertFalse(sectional.children.exists())

    def test_idempotency(self):
        self._load()
        counts_1 = (
            Category.objects.count(),
            Attribute.objects.count(),
            AttributeValue.objects.count(),
            CategoryAttribute.objects.count(),
        )
        self._load()
        counts_2 = (
            Category.objects.count(),
            Attribute.objects.count(),
            AttributeValue.objects.count(),
            CategoryAttribute.objects.count(),
        )
        self.assertEqual(counts_1, counts_2)

    def test_dry_run_does_not_write(self):
        self._load(dry_run=True)
        self.assertEqual(Category.objects.count(), 0)
        self.assertEqual(Attribute.objects.count(), 0)
        self.assertEqual(AttributeValue.objects.count(), 0)
        self.assertEqual(CategoryAttribute.objects.count(), 0)

    def test_missing_file_raises(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command(
                "load_shopify_taxonomy",
                categories="/nonexistent.json",
                attributes=ATTRIBUTES,
            )

    def test_invalid_structure_raises(self):
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"nope": []}, f)
            tmp = f.name
        try:
            from django.core.management.base import CommandError

            with self.assertRaises(CommandError):
                call_command(
                    "load_shopify_taxonomy",
                    categories=tmp,
                    attributes=ATTRIBUTES,
                )
        finally:
            os.unlink(tmp)
