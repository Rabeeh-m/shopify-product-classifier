from django.test import TestCase

from classification.models import Classification, ClassificationAttribute
from products.models import Product, ProductImage, ProductImport
from taxonomy.models import Attribute, AttributeValue


class ModelStrTest(TestCase):
    def test_product_str(self):
        p = Product(external_id="e1", title="Leather Sofa")
        self.assertEqual(str(p), "Leather Sofa")

    def test_product_image_str(self):
        p = Product.objects.create(external_id="e1", title="Sofa")
        img = ProductImage(product=p, url="https://example.com/img.jpg")
        self.assertEqual(str(img), "https://example.com/img.jpg")

    def test_product_import_str(self):
        imp = ProductImport(pk=42, status="completed")
        self.assertEqual(str(imp), "Import #42 (completed)")

    def test_classification_str(self):
        p = Product.objects.create(external_id="e1", title="Sofa")
        cls = Classification(product=p, confidence=80.0)
        self.assertIn("Sofa", str(cls))

    def test_classification_attribute_str_with_value(self):
        attr = Attribute.objects.create(name="Color")
        val = AttributeValue.objects.create(attribute=attr, value="Red")
        cls_attr = ClassificationAttribute(
            attribute=attr, value=val, free_text_value=""
        )
        self.assertIn("Color", str(cls_attr))
        self.assertIn("Red", str(cls_attr))

    def test_classification_attribute_str_with_free_text(self):
        attr = Attribute.objects.create(name="Brand")
        cls_attr = ClassificationAttribute(attribute=attr, free_text_value="Acme")
        self.assertIn("Brand", str(cls_attr))
        self.assertIn("Acme", str(cls_attr))
