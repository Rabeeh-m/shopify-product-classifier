from django.test import TestCase

from classification.models import Classification, ClassificationAttribute
from products.models import Product, ProductImage
from taxonomy.models import Attribute, AttributeValue, Category, CategoryAttribute


class ProductModelTest(TestCase):
    def test_create_product_defaults_to_pending(self):
        product = Product.objects.create(
            external_id="shopify-123",
            title="Test Product",
        )
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.description, "")
        self.assertEqual(product.brand, "")
        self.assertEqual(product.product_type, "")
        self.assertEqual(product.raw_data, {})

    def test_product_str(self):
        product = Product.objects.create(
            external_id="shopify-456",
            title="Nice Shirt",
        )
        self.assertEqual(str(product), "Nice Shirt")

    def test_product_image_belongs_to_product(self):
        product = Product.objects.create(
            external_id="shopify-789",
            title="Image Test",
        )
        image = ProductImage.objects.create(
            product=product,
            url="https://example.com/img.jpg",
        )
        self.assertEqual(image.product, product)
        self.assertIn(image, product.images.all())


class ClassificationModelTest(TestCase):
    def test_one_to_one_enforced(self):
        product = Product.objects.create(
            external_id="clf-1",
            title="Classifier Test",
        )
        Classification.objects.create(
            product=product,
            confidence=0.95,
        )
        with self.assertRaises(Exception):
            Classification.objects.create(
                product=product,
                confidence=0.80,
            )

    def test_classification_defaults(self):
        product = Product.objects.create(
            external_id="clf-2",
            title="Defaults Test",
        )
        clf = Classification.objects.create(
            product=product,
            confidence=0.7,
        )
        self.assertEqual(clf.status, Classification.Status.NEEDS_REVIEW)
        self.assertIsNone(clf.category)
        self.assertIsNone(clf.reviewed_by)
        self.assertEqual(clf.alternatives, [])

    def test_classification_attribute_free_text(self):
        product = Product.objects.create(
            external_id="clf-3",
            title="Attr Test",
        )
        clf = Classification.objects.create(
            product=product,
            confidence=0.6,
        )
        attr = Attribute.objects.create(name="Color")
        ca = ClassificationAttribute.objects.create(
            classification=clf,
            attribute=attr,
            free_text_value="Midnight Blue",
        )
        self.assertIsNone(ca.value)
        self.assertEqual(ca.free_text_value, "Midnight Blue")


class CategoryModelTest(TestCase):
    def test_parent_child_relationship(self):
        root = Category.objects.create(
            name="Clothing",
            full_path="Clothing",
        )
        child = Category.objects.create(
            name="Shirts",
            full_path="Clothing > Shirts",
            parent=root,
        )
        self.assertEqual(child.parent, root)
        self.assertIn(child, root.children.all())

    def test_category_str(self):
        cat = Category.objects.create(
            name="Shoes",
            full_path="Clothing > Shoes",
        )
        self.assertEqual(str(cat), "Clothing > Shoes")

    def test_category_protect_on_delete(self):
        root = Category.objects.create(
            name="Electronics",
            full_path="Electronics",
        )
        Category.objects.create(
            name="Phones",
            full_path="Electronics > Phones",
            parent=root,
        )
        with self.assertRaises(Exception):
            root.delete()

    def test_attribute_value_unique_together(self):
        attr = Attribute.objects.create(name="Material")
        AttributeValue.objects.create(attribute=attr, value="Cotton")
        with self.assertRaises(Exception):
            AttributeValue.objects.create(attribute=attr, value="Cotton")

    def test_category_attribute_through_table(self):
        cat = Category.objects.create(
            name="Hats",
            full_path="Hats",
        )
        attr = Attribute.objects.create(name="Size")
        ca = CategoryAttribute.objects.create(category=cat, attribute=attr)
        self.assertEqual(ca.category, cat)
        self.assertEqual(ca.attribute, attr)
        self.assertIn(ca, cat.category_attributes.all())
