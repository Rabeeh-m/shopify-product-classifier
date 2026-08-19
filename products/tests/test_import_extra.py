import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from products.models import Product
from products.services.import_service import ParseError, import_products

TEST_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class ImportServiceEdgeCasesTest(TestCase):
    def test_file_size_exceeded(self):
        big_csv = b"title\n" + b"x" * (11 * 1024 * 1024)
        upload = SimpleUploadedFile("big.csv", big_csv, content_type="text/csv")
        with self.assertRaises(ParseError) as ctx:
            import_products(upload, "big.csv")
        self.assertTrue(any("exceeds" in e for e in ctx.exception.errors))

    def test_header_only_imports_zero(self):
        csv_data = b"title,description,brand\n"
        upload = SimpleUploadedFile(
            "header_only.csv", csv_data, content_type="text/csv"
        )
        import_obj = import_products(upload, "header_only.csv")
        self.assertEqual(import_obj.imported_rows, 0)
        self.assertEqual(import_obj.total_rows, 0)

    def test_unknown_columns_warning(self):
        csv_data = b"title,unknown_col\nShirt,stuff\n"
        upload = SimpleUploadedFile("unknown.csv", csv_data, content_type="text/csv")
        import_obj = import_products(upload, "unknown.csv")
        self.assertEqual(import_obj.imported_rows, 1)

    def test_none_header_value(self):
        from products.services.import_service import _normalize_header

        self.assertEqual(_normalize_header(None), "")

    def test_multiple_image_separators(self):
        csv_data = (
            b"title,image_urls\n" b"Shirt,http://a.com|http://b.com|http://c.com\n"
        )
        upload = SimpleUploadedFile("multi.csv", csv_data, content_type="text/csv")
        import_products(upload, "multi.csv")
        product = Product.objects.get(title="Shirt")
        self.assertEqual(product.images.count(), 3)

    def test_single_image_no_separator(self):
        csv_data = b"title,image_urls\nShirt,http://a.com/img.jpg\n"
        upload = SimpleUploadedFile("single.csv", csv_data, content_type="text/csv")
        import_products(upload, "single.csv")
        product = Product.objects.get(title="Shirt")
        self.assertEqual(product.images.count(), 1)

    def test_empty_image_urls_field(self):
        csv_data = b"title,image_urls\nShirt,\n"
        upload = SimpleUploadedFile("noimg.csv", csv_data, content_type="text/csv")
        import_products(upload, "noimg.csv")
        product = Product.objects.get(title="Shirt")
        self.assertEqual(product.images.count(), 0)

    def test_empty_title_whitespace_only(self):
        csv_data = b"title\n   \nShirt\n"
        upload = SimpleUploadedFile("ws.csv", csv_data, content_type="text/csv")
        import_obj = import_products(upload, "ws.csv")
        self.assertEqual(import_obj.imported_rows, 1)
        self.assertEqual(import_obj.failed_rows, 1)
