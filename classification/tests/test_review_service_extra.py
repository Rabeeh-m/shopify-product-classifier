import os

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from classification.models import Classification, ClassificationAttribute
from classification.services.review_service import (
    _build_correction_notes,
    correct_classification,
)
from products.models import Product
from taxonomy.models import Attribute, Category, CategoryAttribute

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "..",
    "taxonomy",
    "fixtures",
    "sample_taxonomy.json",
)


def _load_taxonomy():
    call_command("load_taxonomy", source=FIXTURE_PATH)


class CorrectClassificationErrorBranchesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()
        cls.user = User.objects.create_user(username="reviewer", password="pass123")
        cls.cat = Category.objects.first()

    def _make_classification(self, **kwargs):
        p = Product.objects.create(external_id="ext-1", title="Test Product")
        defaults = {
            "category": self.cat,
            "confidence": 80.0,
            "status": Classification.Status.NEEDS_REVIEW,
        }
        defaults.update(kwargs)
        return Classification.objects.create(product=p, **defaults)

    def test_correct_empty_attribute_name_skipped(self):
        cls = self._make_classification()
        result = correct_classification(
            cls,
            self.user,
            attributes=[{"name": "", "value": "Brown"}],
        )
        self.assertEqual(result.status, Classification.Status.APPROVED)
        self.assertEqual(result.attributes.count(), 0)

    def test_correct_free_text_value(self):
        cls = self._make_classification()
        result = correct_classification(
            cls,
            self.user,
            attributes=[{"name": "Color", "value": "CustomTeal"}],
        )
        self.assertEqual(result.status, Classification.Status.APPROVED)
        attr = result.attributes.first()
        self.assertEqual(attr.free_text_value, "CustomTeal")
        self.assertIsNone(attr.value)

    def test_correct_with_existing_value(self):
        cls = self._make_classification()
        result = correct_classification(
            cls,
            self.user,
            attributes=[{"name": "Color", "value": "Brown"}],
        )
        self.assertEqual(result.status, Classification.Status.APPROVED)
        attr = result.attributes.first()
        self.assertIsNotNone(attr.value)
        self.assertEqual(attr.value.value, "Brown")

    def test_correct_replaces_attributes(self):
        cls = self._make_classification()
        brand_attr = Attribute.objects.get_or_create(name="Brand")[0]
        CategoryAttribute.objects.get_or_create(category=self.cat, attribute=brand_attr)
        ClassificationAttribute.objects.create(
            classification=cls,
            attribute=Attribute.objects.get(name="Color"),
            free_text_value="Old",
        )
        result = correct_classification(
            cls,
            self.user,
            attributes=[{"name": "Brand", "value": "Acme"}],
        )
        self.assertEqual(result.attributes.count(), 1)
        self.assertEqual(result.attributes.first().attribute.name, "Brand")


class BuildCorrectionNotesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _load_taxonomy()

    def test_notes_category_changed(self):
        old_cat = Category.objects.first()
        new_cat = Category.objects.last()
        p = Product.objects.create(external_id="ext-1", title="Test Product")
        cls = Classification.objects.create(
            product=p,
            category=old_cat,
            confidence=80.0,
        )
        notes = _build_correction_notes(
            cls, new_cat, [{"name": "Color", "value": "Blue"}]
        )
        self.assertIn("Category changed from", notes)
        self.assertIn(old_cat.full_path, notes)
        self.assertIn(new_cat.full_path, notes)
        self.assertIn("Attributes updated", notes)

    def test_notes_category_set(self):
        new_cat = Category.objects.first()
        p = Product.objects.create(external_id="ext-2", title="Test Product 2")
        cls = Classification.objects.create(
            product=p,
            category=None,
            confidence=80.0,
        )
        notes = _build_correction_notes(cls, new_cat, None)
        self.assertIn("Category set to", notes)
        self.assertIn(new_cat.full_path, notes)

    def test_notes_approved_with_corrections(self):
        p = Product.objects.create(external_id="ext-3", title="Test Product 3")
        cls = Classification.objects.create(
            product=p,
            confidence=80.0,
        )
        notes = _build_correction_notes(cls, None, None)
        self.assertEqual(notes, "Approved with corrections")

    def test_notes_attributes_only(self):
        p = Product.objects.create(external_id="ext-4", title="Test Product 4")
        cls = Classification.objects.create(
            product=p,
            confidence=80.0,
        )
        notes = _build_correction_notes(cls, None, [{"name": "X"}])
        self.assertEqual(notes, "Attributes updated")
