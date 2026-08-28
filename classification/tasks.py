import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone as tz

from products.models import Product, ProductImage, ProductImport

logger = logging.getLogger(__name__)

IMPORT_BATCH_SIZE = getattr(settings, "IMPORT_BATCH_SIZE", 250)


def _rule_classify(product):
    """Try the instant vendor mapping. Returns True if classified+saved."""
    from classification.models import Classification
    from classification.services.persistence import save_classification
    from classification.services.rules import try_rule_classification

    result = try_rule_classification(product)
    if result is None:
        return False
    save_classification(
        product, result, source=Classification.Source.RULE
    )
    return True


def _ai_classify_safe(product):
    """AI fallback wrapper returning (product_id, error_or_None)."""
    from classification.models import Classification
    from classification.services.classifier import classify_product
    from classification.services.persistence import save_classification

    try:
        save_classification(
            product,
            classify_product(product),
            source=Classification.Source.AI,
        )
        return (product.id, None)
    except Exception as exc:
        return (product.id, str(exc)[:500])


def _requeue_stale_processing(products=None):
    """Reset products stuck in 'processing' back to 'pending'.

    A previous run may have died mid-way (e.g. the import's daemon thread
    being recycled on a server restart), leaving products permanently in
    'processing'. Requeueing any that have been processing longer than the
    stale timeout lets a fresh run pick them up again.
    """
    from django.utils import timezone as _tz

    timeout = float(getattr(settings, "PROCESSING_STALE_TIMEOUT_SECONDS", 300))
    stale_cutoff = _tz.now() - timedelta(seconds=timeout)

    qs = Product.objects.filter(status=Product.Status.PROCESSING)
    if products is not None:
        ids = {p.id for p in products}
        qs = qs.filter(id__in=ids)
    stale = qs.filter(
        processing_started_at__lt=stale_cutoff
    ).values_list("id", flat=True)
    stale_ids = list(stale)
    if stale_ids:
        Product.objects.filter(id__in=stale_ids).update(
            status=Product.Status.PENDING,
            processing_started_at=None,
        )
        logger.info("Requeued %d stale 'processing' product(s)", len(stale_ids))
    return stale_ids


def process_products(product_ids=None, import_id=None):
    """Classify products in place: vendor rules inline, AI via thread pool.

    Per-product failures are recorded and never stop the batch. Products left
    'processing' by a previously interrupted run are requeued and retried.
    """
    # Recover products stuck by a previously interrupted (daemon-thread) run.
    _requeue_stale_processing()

    concurrency_limit = getattr(settings, "CLASSIFICATION_CONCURRENCY_LIMIT", 5)

    # "failed" is included so re-runs (classify_products) retry products
    # whose previous attempt failed (e.g. transient AI/quota errors).
    qs = Product.objects.filter(status__in=["pending", "processing", "failed"])
    if import_id is not None:
        qs = qs.filter(product_import_id=import_id)
    if product_ids:
        qs = qs.filter(id__in=product_ids)
    products = list(qs.prefetch_related("images"))

    if not products:
        return {"processed": 0, "failed": 0}

    Product.objects.filter(id__in=[p.id for p in products]).update(
        status=Product.Status.PROCESSING, processing_started_at=tz.now()
    )

    failed_ids = []
    needs_ai = []

    # Pass 1 — instant vendor-rule mappings (no AI, no threads).
    for product in products:
        try:
            if not _rule_classify(product):
                needs_ai.append(product)
        except Exception as exc:
            failed_ids.append((product.id, str(exc)[:500]))
            logger.exception("Rule pass failed for product %d", product.id)

    # Pass 2 — network-bound AI calls paced by the shared rate limiter.
    with ThreadPoolExecutor(max_workers=concurrency_limit) as executor:
        futures = {executor.submit(_ai_classify_safe, p): p for p in needs_ai}
        for future in as_completed(futures):
            product_id, error = future.result()
            if error is not None:
                failed_ids.append((product_id, error))

    failed_map = dict(failed_ids)
    succeeded = [p.id for p in products if p.id not in failed_map]
    if succeeded:
        # Also clear any error left over from a previous failed attempt.
        Product.objects.filter(id__in=succeeded).update(
            processing_started_at=None, error_message=""
        )

    if failed_ids:
        failures = [
            Product(
                id=pid,
                status=Product.Status.FAILED,
                error_message=error_text,
                processing_started_at=None,
            )
            for pid, error_text in failed_ids
        ]
        Product.objects.bulk_update(
            failures, ["status", "error_message", "processing_started_at"]
        )
        for pid, error_text in failed_ids:
            logger.error("Product %d failed: %s", pid, error_text)

    logger.info(
        "Classification complete: %d processed, %d failed",
        len(products),
        len(failed_ids),
    )
    return {"processed": len(products), "failed": len(failed_ids)}


def import_products(import_id):
    """Parse the uploaded file and bulk-create products + images."""
    from products.services.import_service import (
        ParseError,
        _map_row,
        parse_rows_from_import,
    )

    import_obj = ProductImport.objects.get(pk=import_id)

    try:
        _headers, rows = parse_rows_from_import(import_obj)
    except ParseError as exc:
        import_obj.status = ProductImport.Status.FAILED
        import_obj.error_log = [{"error": e} for e in exc.errors]
        import_obj.save(update_fields=["status", "error_log"])
        return {"total": 0, "imported": 0, "failed": 0}

    total = len(rows)
    import_obj.total_rows = total
    import_obj.save(update_fields=["total_rows"])

    total_imported = 0
    total_failed = 0
    all_errors = []

    for batch_start in range(0, total, IMPORT_BATCH_SIZE):
        batch_rows = rows[batch_start:batch_start + IMPORT_BATCH_SIZE]
        products_to_create = []
        images_by_idx = {}
        batch_errors = []

        for i, row in enumerate(batch_rows):
            mapped = _map_row(row)
            if not mapped["title"]:
                batch_errors.append(
                    {
                        "row": batch_start + i + 2,
                        "error": "Missing required field: title",
                    }
                )
                continue

            idx = len(products_to_create)
            products_to_create.append(
                Product(
                    product_import=import_obj,
                    external_id=mapped["external_id"],
                    title=mapped["title"],
                    description=mapped["description"],
                    brand=mapped["brand"],
                    product_type=mapped["product_type"],
                    raw_data=row,
                    status=Product.Status.PENDING,
                )
            )
            if mapped["image_urls"]:
                images_by_idx[idx] = mapped["image_urls"]

        with transaction.atomic():
            created = Product.objects.bulk_create(products_to_create)
            image_objs = []
            for idx, urls in images_by_idx.items():
                if idx < len(created):
                    for url in urls:
                        image_objs.append(
                            ProductImage(product=created[idx], url=url)
                        )
            if image_objs:
                ProductImage.objects.bulk_create(image_objs)

        total_imported += len(created)
        total_failed += len(batch_errors)
        all_errors.extend(batch_errors)

        import_obj.imported_rows = total_imported
        import_obj.failed_rows = total_failed
        import_obj.save(update_fields=["imported_rows", "failed_rows"])

    import_obj.status = ProductImport.Status.COMPLETED
    import_obj.imported_rows = total_imported
    import_obj.failed_rows = total_failed
    import_obj.error_log = all_errors
    import_obj.completed_at = tz.now()
    import_obj.save(
        update_fields=[
            "status",
            "imported_rows",
            "failed_rows",
            "error_log",
            "completed_at",
        ]
    )

    logger.info(
        "Import #%d complete: %d imported, %d failed of %d rows",
        import_id,
        total_imported,
        total_failed,
        total,
    )
    return {
        "total": total,
        "imported": total_imported,
        "failed": total_failed,
    }


def _recover_import_after_crash(import_id):
    """Reset an import's in-flight 'processing' products back to 'pending'.

    Called when a background import crashes (e.g. interrupted during
    interpreter shutdown) so products aren't left orphaned in 'processing';
    a later run will retry them.
    """
    stuck = Product.objects.filter(
        product_import_id=import_id, status=Product.Status.PROCESSING
    )
    updated = stuck.update(status=Product.Status.PENDING, processing_started_at=None)
    if updated:
        logger.info("Reset %d stuck 'processing' product(s) on crash", updated)
    return updated


def start_import_background(import_id):
    """Run import + classification on a background thread so the upload
    request returns immediately.

    The thread is deliberately non-daemon: a daemon thread is killed abruptly
    during interpreter shutdown (e.g. the dev server auto-reload), which can
    interrupt process_products mid-run and leave products stuck in
    'processing'. A non-daemon thread is joined during shutdown, so pending
    work finishes (or at least records a clean failure) instead of crashing.
    """
    def _run():
        try:
            import_products(import_id)
            process_products(import_id=import_id)
        except Exception:
            logger.exception("Background import %d crashed", import_id)
            _recover_import_after_crash(import_id)
            ProductImport.objects.filter(pk=import_id).update(
                status=ProductImport.Status.FAILED
            )

    threading.Thread(
        target=_run, name=f"import-{import_id}", daemon=False
    ).start()
