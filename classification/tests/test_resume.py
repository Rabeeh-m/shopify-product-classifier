from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from classification.tasks import _recover_import_after_crash, _requeue_stale_processing
from products.models import Product, ProductImport


def _product(title, status_code="pending", import_obj=None):
    return Product.objects.create(
        external_id=f"ext-{title}",
        title=title,
        description="test",
        status=status_code,
        product_import=import_obj,
    )


@override_settings(PROCESSING_STALE_TIMEOUT_SECONDS=300)
class RequeueStaleProcessingTest(TestCase):
    def test_recent_processing_is_not_requeued(self):
        p = _product("Fresh", status_code="processing")
        Product.objects.filter(pk=p.pk).update(
            processing_started_at=timezone.now() - timedelta(seconds=30)
        )
        _requeue_stale_processing()
        p.refresh_from_db()
        self.assertEqual(p.status, "processing")

    def test_stale_processing_is_requeued_to_pending(self):
        p = _product("Stale", status_code="processing")
        Product.objects.filter(pk=p.pk).update(
            processing_started_at=timezone.now() - timedelta(seconds=99999)
        )
        _requeue_stale_processing()
        p.refresh_from_db()
        self.assertEqual(p.status, "pending")
        self.assertIsNone(p.processing_started_at)


class RecoverImportAfterCrashTest(TestCase):
    def test_resets_processing_products_to_pending(self):
        imp = ProductImport.objects.create(
            file=SimpleUploadedFile("x.csv", b"a,b,c\n")
        )
        stuck = _product("Stuck", status_code="processing", import_obj=imp)
        s_done = _product("Done", status_code="done", import_obj=imp)

        _recover_import_after_crash(imp.id)

        stuck.refresh_from_db()
        s_done.refresh_from_db()
        self.assertEqual(stuck.status, "pending")
        self.assertIsNone(stuck.processing_started_at)
        self.assertEqual(s_done.status, "done")

    def test_other_imports_unaffected(self):
        imp = ProductImport.objects.create(
            file=SimpleUploadedFile("x.csv", b"a,b,c\n")
        )
        other = ProductImport.objects.create(
            file=SimpleUploadedFile("y.csv", b"a,b,c\n")
        )
        stuck_this = _product("Stuck", status_code="processing", import_obj=imp)
        stuck_other = _product(
            "Stuck Other", status_code="processing", import_obj=other
        )

        _recover_import_after_crash(imp.id)

        stuck_this.refresh_from_db()
        stuck_other.refresh_from_db()
        self.assertEqual(stuck_this.status, "pending")
        self.assertEqual(stuck_other.status, "processing")
