from django.test import TestCase

from classification.models import ClassificationAttribute
from classification.serializers import (
    AlternativeSerializer,
    ClassificationAttributeSerializer,
    ProductMinimalSerializer,
)
from products.models import Product
from taxonomy.models import Attribute, AttributeValue, Category


class ProductMinimalSerializerTest(TestCase):
    def test_no_request_builds_plain_urls(self):
        p = Product.objects.create(external_id="ext-1", title="Test")
        p.images.create(url="/media/img.jpg")
        serializer = ProductMinimalSerializer(p)
        self.assertEqual(serializer.data["image_urls"], ["/media/img.jpg"])


class AlternativeSerializerTest(TestCase):
    def test_category_not_found_returns_none(self):
        ctx = {"category_cache": {}}
        serializer = AlternativeSerializer(
            {"category_id": 99999, "confidence": 80.0}, context=ctx
        )
        self.assertIsNone(serializer.data["category"])

    def test_category_cache_hit(self):
        cat = Category.objects.create(id=500, name="Cached", full_path="Cached")
        ctx = {"category_cache": {500: cat}}
        serializer = AlternativeSerializer(
            {"category_id": 500, "confidence": 90.0}, context=ctx
        )
        self.assertEqual(serializer.data["category"]["id"], 500)


class ClassificationAttributeSerializerTest(TestCase):
    def test_str_value_display(self):
        attr = Attribute.objects.create(name="Color")
        val = AttributeValue.objects.create(attribute=attr, value="Red")
        cls_attr = ClassificationAttribute(
            attribute=attr, value=val, free_text_value=""
        )
        serializer = ClassificationAttributeSerializer(cls_attr)
        # AttributeValue.__str__ returns "Color: Red"
        self.assertEqual(serializer.data["value_display"], "Color: Red")

    def test_free_text_display(self):
        attr = Attribute.objects.create(name="Material")
        cls_attr = ClassificationAttribute(
            attribute=attr, value=None, free_text_value="CustomSilk"
        )
        serializer = ClassificationAttributeSerializer(cls_attr)
        self.assertEqual(serializer.data["value_display"], "CustomSilk")
