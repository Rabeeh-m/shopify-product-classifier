import concurrent.futures
import logging
import threading

from celery import chain, shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone as tz

from products.models import Product, ProductImage, ProductImport

logger = logging.getLogger(__name__)

# Number of rows inserted per DB batch in the async import task.
IMPORT_BATCH_SIZE = getattr(settings, "IMPORT_BATCH_SIZE", 250)

# Serializes classification writes across worker threads. SQLite (dev)
# serializes writers anyway, so concurrent save_classification() calls
# only add lock contention; on Postgres the writes are short enough that
# the serialization cost is negligible.
_CLASSIFICATION_WRITE_LOCK = threading.Lock()


def _dispatch_classification_chunks(id_lists):
    """Queue batch tasks to run strictly one after another.

    Concurrent batches would race for SQLite write locks (dev DB) and
    multiply the per-process AI rate limiter (each process gets its own
    15 RPM budget → 429 storms). Chaining keeps a single batch in flight
    regardless of how many worker processes exist.
    """
    signatures = [
        process_product_batch.si(ids) for ids in id_lists if ids
    ]
    if signatures:
        chain(signatures).apply_async()
        logger.info(
            "Dispatched %d classification batch(es) sequentially",
            len(signatures),
        )


def _mark_processing(product_ids):
    now = tz.now()
    Product.objects.filter(
        id__in=product_ids, status__in=["pending", "processing"]
    ).update(
        status=Product.Status.PROCESSING,
        processing_started_at=now,
    )


def _rule_phase(product):
    """Try to classify a product with vendor/keyword rules only.

    Returns True when the product was classified and saved without any
    AI call. Cheap and deterministic — safe to run inline per product.
    """
    from classification.services.candidate_finder import find_candidates
    from classification.services.persistence import save_classification
    from classification.services.rule_classifier import try_rule_classification

    candidates = find_candidates(product)
    rule_response = try_rule_classification(product, candidates)
    if rule_response is None:
        return False

    # Rule-layer confidence is already calibrated (vendor mapping strength,
    # keyword score gaps) and must not be demoted by the data-completeness
    # adjustment meant for AI self-reports — a direct vendor mapping stays
    # authoritative even if the row lacks a description or image.
    final_confidence = float(rule_response["confidence"])
    with _CLASSIFICATION_WRITE_LOCK:
        save_classification(product, rule_response, final_confidence)
    return True


def _run_pipeline(product):
    from classification.services.candidate_finder import (
        CandidateResult,
        find_candidates,
    )
    from classification.services.classifier import classify_product
    from classification.services.confidence import calculate_confidence
    from classification.services.persistence import save_classification
    from classification.services.rule_classifier import try_rule_classification

    candidates = find_candidates(product)

    rule_response = try_rule_classification(product, candidates)
    if rule_response is not None:
        # See _rule_phase: rule confidence passes through unadjusted.
        final_confidence = float(rule_response["confidence"])
        with _CLASSIFICATION_WRITE_LOCK:
            save_classification(product, rule_response, final_confidence)
        return

    if not candidates:
        # Rules missed and keyword narrowing found nothing. Send the AI the
        # whole taxonomy rather than failing the product outright — rare,
        # but keeps unmatchable titles classifiable (they land in needs_review).
        logger.warning(
            "No keyword candidates for '%s'; falling back to full taxonomy",
            product.title,
        )
        from taxonomy.services.cache import get_all_categories

        candidates = [
            CandidateResult(category=cat, score=0.0)
            for cat in get_all_categories()
        ]

    ai_response = classify_product(product, candidates)
    final_confidence = calculate_confidence(product, ai_response)
    with _CLASSIFICATION_WRITE_LOCK:
        save_classification(product, ai_response, final_confidence)


def _run_pipeline_safe(product):
    try:
        _run_pipeline(product)
        return (product.id, None)
    except Exception as exc:
        return (product.id, str(exc)[:500])


@shared_task(bind=True)
def process_product_batch(self, product_ids):
    concurrency_limit = getattr(settings, "CLASSIFICATION_CONCURRENCY_LIMIT", 5)

    products = list(
        Product.objects.filter(
            id__in=product_ids, status__in=["pending", "processing"]
        ).prefetch_related("images")
    )

    if not products:
        return {"processed": 0}

    _mark_processing([p.id for p in products])

    failed_ids = []

    # ------------------------------------------------------------------ #
    # Phase 1 — rules fast path (no AI, no rate limit).                   #
    # Runs inline: ~90%+ of a well-mapped import resolves here, and       #
    # skipping the thread pool avoids DB-writer contention entirely.      #
    # ------------------------------------------------------------------ #
    needs_ai = []
    for product in products:
        try:
            if not _rule_phase(product):
                needs_ai.append(product)
        except Exception as exc:
            failed_ids.append((product.id, str(exc)[:500]))
            logger.exception("Rule phase failed for product %d", product.id)

    # ------------------------------------------------------------------ #
    # Phase 2 — AI fallback for rule misses only.                         #
    # Threads help here because the work is network-bound (Gemini calls   #
    # paced by the shared rate limiter).                                  #
    # ------------------------------------------------------------------ #
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=concurrency_limit
    ) as executor:
        futures = {executor.submit(_run_pipeline_safe, p): p for p in needs_ai}
        for future in concurrent.futures.as_completed(futures):
            product_id, error = future.result()
            if error is not None:
                failed_ids.append((product_id, error))

    succeeded_ids = [
        p.id for p in products if p.id not in {fid for fid, _ in failed_ids}
    ]

    if succeeded_ids:
        Product.objects.filter(id__in=succeeded_ids).update(processing_started_at=None)

    if failed_ids:
        errors_by_id = {fid: err for fid, err in failed_ids}
        failed_products = {
            p.id: p for p in Product.objects.filter(id__in=list(errors_by_id.keys()))
        }

        batch_fail = []
        for pid, error_text in errors_by_id.items():
            product = failed_products[pid]
            batch_fail.append(
                Product(
                    id=pid,
                    status=Product.Status.FAILED,
                    error_message=error_text,
                    processing_started_at=None,
                )
            )
            logger.error(
                "Product %d (%s) failed: %s",
                pid,
                product.title,
                error_text,
            )

        if batch_fail:
            Product.objects.bulk_update(
                batch_fail,
                ["status", "error_message", "processing_started_at"],
            )

    logger.info(
        "Batch processing complete: %d products processed, %d failed",
        len(products),
        len(failed_ids),
    )
    return {"processed": len(products), "failed": len(failed_ids)}


@shared_task(bind=True)
def process_all_pending(self, chunk_size=100):
    pending_ids = list(
        Product.objects.filter(status="pending").values_list("id", flat=True)
    )

    if not pending_ids:
        logger.info("No pending products to classify.")
        return {"processed": 0}

    chunks = [
        pending_ids[i : i + chunk_size]
        for i in range(0, len(pending_ids), chunk_size)
    ]
    _dispatch_classification_chunks(chunks)

    logger.info(
        "Queued %d pending products in %d sequential batch(es)",
        len(pending_ids),
        len(chunks),
    )
    return {"processed": len(pending_ids), "chunks": len(chunks)}


@shared_task(bind=True, max_retries=3)
def import_and_classify_products(self, import_id):
    """Background task: parse the uploaded file, bulk-create products in batches,
    then queue classification batches sequentially.

    Progress is reflected in real time via ProductImport.imported_rows and
    ProductImport.total_rows so the frontend polling loop can show accurate
    numbers.
    """
    from products.services.import_service import (
        ParseError,
        _map_row,
        parse_rows_from_import,
    )

    try:
        import_obj = ProductImport.objects.get(pk=import_id)
    except ProductImport.DoesNotExist:
        logger.error("import_and_classify_products: import %s not found", import_id)
        return

    logger.info("Starting background import for ProductImport #%d", import_id)

    # ------------------------------------------------------------------ #
    # 1. Parse the file (reads from disk via FileField)                   #
    # ------------------------------------------------------------------ #
    try:
        _headers, rows = parse_rows_from_import(import_obj)
    except ParseError as exc:
        logger.error("Parse failed for import #%d: %s", import_id, exc.errors)
        import_obj.status = ProductImport.Status.FAILED
        import_obj.error_log = [{"error": e} for e in exc.errors]
        import_obj.save(update_fields=["status", "error_log"])
        return
    except Exception as exc:
        logger.exception("Unexpected parse error for import #%d", import_id)
        import_obj.status = ProductImport.Status.FAILED
        import_obj.error_log = [{"error": str(exc)}]
        import_obj.save(update_fields=["status", "error_log"])
        return

    total = len(rows)
    import_obj.total_rows = total
    import_obj.save(update_fields=["total_rows"])
    logger.info("Import #%d: %d rows to process", import_id, total)

    # ------------------------------------------------------------------ #
    # 2. Insert rows in batches and queue classification per batch         #
    # ------------------------------------------------------------------ #
    total_imported = 0
    total_failed = 0
    all_errors = []
    classification_chunks = []

    for batch_start in range(0, total, IMPORT_BATCH_SIZE):
        batch_rows = rows[batch_start: batch_start + IMPORT_BATCH_SIZE]

        products_to_create = []
        images_by_idx = {}  # index in products_to_create → list[url]
        failed_in_batch = 0
        batch_errors = []

        for i, row in enumerate(batch_rows):
            row_number = batch_start + i + 2  # 1-indexed, with header row
            mapped = _map_row(row)
            title = mapped["title"]
            if not title:
                failed_in_batch += 1
                batch_errors.append(
                    {"row": row_number, "error": "Missing required field: title"}
                )
                continue

            idx = len(products_to_create)
            products_to_create.append(
                Product(
                    product_import=import_obj,
                    external_id=mapped["external_id"],
                    title=title,
                    description=mapped["description"],
                    brand=mapped["brand"],
                    product_type=mapped["product_type"],
                    raw_data=row,
                    status=Product.Status.PENDING,
                )
            )
            if mapped["image_urls"]:
                images_by_idx[idx] = mapped["image_urls"]

        # Bulk-create products and images in one transaction per batch
        created_products = []
        if products_to_create:
            with transaction.atomic():
                created_products = Product.objects.bulk_create(products_to_create)

                # Build image objects now that we have PKs
                image_objs = []
                for idx, urls in images_by_idx.items():
                    if idx < len(created_products):
                        prod = created_products[idx]
                        for url in urls:
                            image_objs.append(ProductImage(product=prod, url=url))
                if image_objs:
                    ProductImage.objects.bulk_create(image_objs)

        batch_imported = len(created_products)
        total_imported += batch_imported
        total_failed += failed_in_batch
        all_errors.extend(batch_errors)

        # Update progress counters after each batch
        import_obj.imported_rows = total_imported
        import_obj.failed_rows = total_failed
        import_obj.save(update_fields=["imported_rows", "failed_rows"])

        # Dispatch classification for this batch immediately
        if created_products:
            classification_chunks.append([p.id for p in created_products])

        logger.info(
            "Import #%d: batch %d–%d done (%d inserted, %d failed). "
            "Total so far: %d/%d",
            import_id,
            batch_start + 1,
            batch_start + len(batch_rows),
            batch_imported,
            failed_in_batch,
            total_imported,
            total,
        )

    # ------------------------------------------------------------------ #
    # 3. Mark import as completed                                          #
    # ------------------------------------------------------------------ #
    # Classification batches are queued sequentially so a single batch is
    # ever in flight (avoids SQLite lock contention and AI rate-limit
    # multiplication across worker processes).
    _dispatch_classification_chunks(classification_chunks)
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
        "Import #%d complete: %d imported, %d failed out of %d total rows",
        import_id,
        total_imported,
        total_failed,
        total,
    )
    return {
        "import_id": import_id,
        "total": total,
        "imported": total_imported,
        "failed": total_failed,
    }
