import os

from django.core.management import call_command
from django.test import TestCase

from taxonomy.models import Attribute, AttributeValue, Category, CategoryAttribute

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "fixtures", "sample_taxonomy.json"
)


class LoadTaxonomyTest(TestCase):
    def setUp(self):
        self.fixture_path = FIXTURE_PATH

    def _count_data(self):
        return {
            "categories": Category.objects.count(),
            "attributes": Attribute.objects.count(),
            "values": AttributeValue.objects.count(),
            "cat_attrs": CategoryAttribute.objects.count(),
        }

    def test_load_creates_expected_counts(self):
        call_command("load_taxonomy", source=self.fixture_path)

        counts = self._count_data()
        self.assertEqual(counts["categories"], 75)
        self.assertEqual(counts["attributes"], 11)
        self.assertEqual(counts["values"], 65)
        self.assertGreaterEqual(counts["cat_attrs"], 187)

    def test_idempotency(self):
        call_command("load_taxonomy", source=self.fixture_path)
        counts_after_first = self._count_data()

        call_command("load_taxonomy", source=self.fixture_path)
        counts_after_second = self._count_data()

        self.assertEqual(counts_after_first, counts_after_second)

    def test_dry_run_does_not_write(self):
        call_command("load_taxonomy", source=self.fixture_path, dry_run=True)

        counts = self._count_data()
        self.assertEqual(counts["categories"], 0)
        self.assertEqual(counts["attributes"], 0)
        self.assertEqual(counts["values"], 0)
        self.assertEqual(counts["cat_attrs"], 0)

    def test_sofas_category_parent_chain(self):
        call_command("load_taxonomy", source=self.fixture_path)

        sofas = Category.objects.get(name="Sofas & Loveseats")
        self.assertEqual(sofas.full_path, "Furniture > Sofas & Loveseats")
        self.assertIsNotNone(sofas.parent)
        self.assertEqual(sofas.parent.name, "Furniture")
        self.assertIsNone(sofas.parent.parent)

    def test_sofas_has_linked_attributes(self):
        call_command("load_taxonomy", source=self.fixture_path)

        sofas = Category.objects.get(name="Sofas & Loveseats")
        linked_attrs = Attribute.objects.filter(category_attributes__category=sofas)
        attr_names = set(linked_attrs.values_list("name", flat=True))
        self.assertIn("Color", attr_names)
        self.assertIn("Material", attr_names)
        self.assertIn("Pattern", attr_names)

    def test_nested_category_full_path(self):
        call_command("load_taxonomy", source=self.fixture_path)

        bunk = Category.objects.get(name="Bunk Beds")
        self.assertEqual(
            bunk.full_path,
            "Furniture > Beds & Accessories > Beds & Bed Frames > Bunk Beds",
        )

    def test_attribute_values_created(self):
        call_command("load_taxonomy", source=self.fixture_path)

        color = Attribute.objects.get(name="Color")
        values = set(color.values.values_list("value", flat=True))
        self.assertIn("Red", values)
        self.assertIn("Blue", values)
        self.assertEqual(color.values.count(), 10)

    def test_invalid_source_file(self):
        with self.assertRaises(Exception):
            call_command("load_taxonomy", source="/nonexistent/path.json")

    def test_invalid_json(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            f.flush()
            try:
                with self.assertRaises(Exception):
                    call_command("load_taxonomy", source=f.name)
            finally:
                os.unlink(f.name)

    def test_missing_required_keys(self):
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"categories": []}, f)
            f.flush()
            try:
                with self.assertRaises(Exception):
                    call_command("load_taxonomy", source=f.name)
            finally:
                os.unlink(f.name)
