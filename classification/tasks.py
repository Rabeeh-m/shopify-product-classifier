import concurrent.futures
import logging

from celery import shared_task

from products.models import Product

logger = logging.getLogger(__name__)

_MAX_WORKERS = 5


def _run_pipeline(product):
    """Run the full classification pipeline for a single product.

    Steps: candidate_finder -> classifier -> confidence -> persistence.
    Each step is isolated so that an error in one step propagates up
    to the caller (process_product_batch) for logging and status update.
    """
    from classification.services.candidate_finder import find_candidates
    from classification.services.classifier import classify_product
    from classification.services.confidence import calculate_confidence
    from classification.services.persistence import save_classification

    candidates = find_candidates(product)
    ai_response = classify_product(product, candidates)
    final_confidence = calculate_confidence(product, ai_response)
    save_classification(product, ai_response, final_confidence)


def _run_pipeline_safe(product):
    """Run the pipeline, returning (product_id, error_string|None).

    This is the function submitted to the thread pool.  It catches all
    exceptions and returns them rather than updating the DB directly,
    avoiding SQLite thread-safety issues during testing.
    """
    try:
        _run_pipeline(product)
        return (product.id, None)
    except Exception as exc:
        return (product.id, str(exc)[:500])


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def process_product_batch(self, product_ids):
    """Process a batch of product IDs through the classification pipeline.

    Runs the pipeline concurrently using a thread pool for throughput.
    Each product is processed independently — a failure in one product is
    caught, logged, and does not prevent other products from completing.

    On success: product.status is set to 'done' or 'needs_review' by
    save_classification.
    On failure: product.status = 'failed', product.error_message stores
    the exception text.
    """
    products = list(
        Product.objects.filter(id__in=product_ids, status__in=["pending", "processing"])
    )

    if not products:
        return {"processed": 0}

    failed_ids = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_run_pipeline_safe, p): p for p in products}
        for future in concurrent.futures.as_completed(futures):
            product_id, error = future.result()
            if error is not None:
                failed_ids.append((product_id, error))

    if failed_ids:
        ids_to_fail = [fid for fid, _ in failed_ids]
        errors_by_id = {fid: err for fid, err in failed_ids}
        for pid in ids_to_fail:
            Product.objects.filter(id=pid).update(
                status=Product.Status.FAILED,
                error_message=errors_by_id[pid],
            )
            product = Product.objects.get(id=pid)
            logger.exception(
                "Classification failed for product %d (%s): %s",
                pid,
                product.title,
                errors_by_id[pid],
            )

    logger.info(
        "Batch processing complete: %d products processed, %d failed",
        len(products),
        len(failed_ids),
    )
    return {"processed": len(products), "failed": len(failed_ids)}


@shared_task(bind=True)
def process_all_pending(self, chunk_size=100):
    """Query pending products and dispatch them in chunks.

    Fetches up to chunk_size pending products, dispatches
    process_product_batch for that chunk, and re-enqueues itself if
    more pending products remain.  This is the resumable loop pattern
    that ensures all pending products eventually get processed.
    """
    pending_ids = list(
        Product.objects.filter(status="pending").values_list("id", flat=True)[
            :chunk_size
        ]
    )

    if not pending_ids:
        logger.info("No pending products to classify.")
        return {"processed": 0, "remaining": 0}

    process_product_batch.delay(pending_ids)

    remaining = Product.objects.filter(status="pending").count()
    if remaining > 0:
        process_all_pending.delay(chunk_size=chunk_size)

    return {"processed": len(pending_ids), "remaining": remaining}
