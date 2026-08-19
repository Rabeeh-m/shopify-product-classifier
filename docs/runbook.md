# Runbook — Batch Recovery and Stuck Products

> Cross-references: [README.md](../README.md) | [Security](security.md) | [API](api.md) | [Architecture](architecture.md)

If the Celery worker crashes, gets killed, or is restarted during a
classification run, some products may be stuck in "processing" status.
The system handles this automatically, but here's what to know.

## What happens automatically

A background task (Celery beat) runs every 15 minutes. It finds any
product stuck in "processing" for more than 30 minutes and puts it back
in the "pending" queue so the next worker run picks it up.

Products that keep failing are tracked with a retry counter. After 3
failures (configurable), a product is marked "failed" permanently and
will not be retried.

## Manual recovery

If you don't want to wait for the automatic check, run these commands
on the server:

### 1. Restart the Celery worker

```bash
celery -A config worker --loglevel=info
```

### 2. Requeue stuck products (optional)

```bash
python manage.py requeue_stuck_products
```

You can also adjust the time threshold:

```bash
python manage.py requeue_stuck_products --older-than-minutes=15
```

### 3. Re-trigger classification (optional)

If no pending products exist (everything was already picked up but the
worker died before completing), re-trigger classification:

```bash
python manage.py shell -c "from classification.tasks import process_all_pending; process_all_pending.delay()"
```

## Checking status

Visit `/api/classification/jobs/status/` or run:

```bash
python manage.py shell -c "
from products.models import Product
from django.db.models import Count, Q
counts = Product.objects.aggregate(
    pending=Count('id', filter=Q(status='pending')),
    processing=Count('id', filter=Q(status='processing')),
    done=Count('id', filter=Q(status='done')),
    needs_review=Count('id', filter=Q(status='needs_review')),
    failed=Count('id', filter=Q(status='failed')),
)
print(counts)
"
```

## Configuration

| Setting | Default | Description |
|---|---|---|
| `CLASSIFICATION_MAX_RETRIES` | 3 | Max times a product is retried before permanent failure |
| Stuck threshold | 30 min | How long before a "processing" product is considered stuck |
| Beat schedule | Every 15 min | How often the stuck-product check runs |
