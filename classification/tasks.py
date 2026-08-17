import concurrent.futures
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone as tz

from products.models import Product

logger = logging.getLogger(__name__)

_MAX_WORKERS = 5


def _mark_processing(product_ids):
    """Atomically set status='processing' and processing_started_at for a batch.

    Uses update() to avoid race conditions when multiple workers pick up
    the same batch (though Celery should prevent this, it's defensive).
    """
    now = tz.now()
    Product.objects.filter(
        id__in=product_ids, status__in=["pending", "processing"]
    ).update(
        status=Product.Status.PROCESSING,
        processing_started_at=now,
    )


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
    save_classification, and processing_started_at is cleared.
    On failure: product.status = 'failed', product.error_message stores
    the exception text, and retry_count is incremented.  If retry_count
    reaches CLASSIFICATION_MAX_RETRIES the product stays in 'failed'
    permanently.
    """
    products = list(
        Product.objects.filter(id__in=product_ids, status__in=["pending", "processing"])
    )

    if not products:
        return {"processed": 0}

    _mark_processing([p.id for p in products])

    failed_ids = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_run_pipeline_safe, p): p for p in products}
        for future in concurrent.futures.as_completed(futures):
            product_id, error = future.result()
            if error is not None:
                failed_ids.append((product_id, error))

    failed_set = {fid for fid, _ in failed_ids}
    succeeded_ids = [p.id for p in products if p.id not in failed_set]

    if succeeded_ids:
        Product.objects.filter(id__in=succeeded_ids).update(processing_started_at=None)

    max_retries = getattr(settings, "CLASSIFICATION_MAX_RETRIES", 3)

    if failed_ids:
        errors_by_id = {fid: err for fid, err in failed_ids}
        for pid in errors_by_id:
            product = Product.objects.get(id=pid)
            new_retry_count = product.retry_count + 1
            if new_retry_count >= max_retries:
                Product.objects.filter(id=pid).update(
                    status=Product.Status.FAILED,
                    error_message=errors_by_id[pid],
                    retry_count=new_retry_count,
                    processing_started_at=None,
                )
                logger.error(
                    "Product %d (%s) permanently failed after %d retries: %s",
                    pid,
                    product.title,
                    new_retry_count,
                    errors_by_id[pid],
                )
            else:
                Product.objects.filter(id=pid).update(
                    status=Product.Status.PENDING,
                    error_message=errors_by_id[pid],
                    retry_count=new_retry_count,
                    processing_started_at=None,
                )
                logger.warning(
                    "Product %d (%s) requeued (retry %d/%d): %s",
                    pid,
                    product.title,
                    new_retry_count,
                    max_retries,
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
