# Stage 9: Stuck-Product Recovery & Retry Limiting — COMPLETE

Ready for Stage 10.

## Completed
- `products/models.py` — added `processing_started_at` (DateTimeField, nullable) and `retry_count` (PositiveIntegerField, default=0)
- `products/migrations/0004_add_processing_tracking_fields.py` — migration for new fields
- `config/settings/base.py` — `CLASSIFICATION_MAX_RETRIES = 3` setting
- `classification/tasks.py` — `_mark_processing()` sets status='processing' + timestamp; retry logic increments retry_count, requeues below max, permanently fails at/above max; clears `processing_started_at` on success
- `products/management/commands/requeue_stuck_products.py` — finds stuck 'processing' products (>30 min), uses `select_for_update(skip_locked=True)`, respects retry_count/max_retries
- `products/tasks.py` — `requeue_stuck_products_task` Celery task wrapping the management command
- `config/celery.py` — beat schedule runs `requeue_stuck_products_task` every 15 minutes
- `docs/runbook.md` — "Recovering from a stopped batch" operational guide
- 15 new Stage 9 tests (processing status, retry logic, permanent failure, stuck recovery, crash end-to-end)
- 152 total tests passing, all linting clean
