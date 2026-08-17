# Performance

## Query Count Improvements (Stage 15)

### Review List Endpoint (25 classifications per page)

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| DB queries | 29 | 5 | **83%** |
| Time (approx) | 32ms | 30ms | — |

**Before:** Each of the 25 classification results triggered a separate `Category.objects.get()` to resolve its alternative category — classic N+1 pattern. With 25 items each having 1 alternative, that's 25 redundant queries.

**After:** The view bulk-loads all unique alternative category IDs for the entire page in a single `Category.objects.filter(id__in=...)` query. The serializer cache (`category_cache` in DRF context) is shared across all serializer instances in the same request, preventing any redundant lookups.

**Remaining 5 queries:**
1. `COUNT(*)` for pagination
2. Main classification SELECT (with `select_related` for product, category, reviewed_by)
3. Prefetch `classificationattribute`
4. Prefetch `productimage`
5. Bulk-load alternative categories

### Candidate Finder (10 products)

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| DB queries | 10 | 0 (after warm) | **100%** |
| Time (approx) | 33ms | 20ms | **39%** |

**Before:** `find_candidates(product)` called `Category.objects.all()` on every invocation. In a batch of 10 products, that's 10 identical queries.

**After:** `taxonomy.services.cache.get_all_categories()` loads the full taxonomy into Django's cache framework (LocMem in dev, Redis in production) with a configurable TTL (`TAXONOMY_CACHE_TTL`, default 3600s). Subsequent calls return the cached list with zero DB queries.

## Concurrency Tuning

### Setting

`CLASSIFICATION_CONCURRENCY_LIMIT` (env var, default 5) controls the `ThreadPoolExecutor` max workers in `process_product_batch`. Tune this based on:

- AI provider rate limits (start with 5, increase if no rate-limiting errors)
- Available CPU cores (for CPU-bound parsing work)
- Database connection pool size (each thread needs a connection)

### Batch Error Handling

Failed products in a batch no longer trigger individual `Product.objects.get()` calls. Instead, all failed product IDs are collected, then a single bulk query loads them. Status updates use `bulk_update()` instead of per-product `save()`.

## Taxonomy Caching

### How It Works

- `taxonomy.services.cache.get_all_categories()` — Returns all `Category` objects, cached via Django's cache framework
- First call hits DB, subsequent calls serve from cache
- Cache key: `taxonomy:all_categories`
- TTL: configurable via `TAXONOMY_CACHE_TTL` (default 3600s / 1 hour)

### Cache Invalidation

- `load_taxonomy` management command invalidates the cache after a successful non-dry-run load
- `taxonomy.services.cache.invalidate_taxonomy_cache()` — explicit invalidation function
- Production uses Redis-backed cache; dev/test uses LocMem

### Configuration

```python
# config/settings/base.py
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# config/settings/prod.py
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
    }
}
```

## Database Indexes

### Added in Stage 15

```python
# classification/models.py — Classification.Meta
indexes = [
    models.Index(
        fields=["status", "-created_at"],
        name="idx_cls_status_created",
    ),
]
```

Covers the review list query pattern: `filter(status='needs_review').order_by('-created_at')`.

### Pre-existing Indexes

| Model | Field(s) | Purpose |
|-------|----------|---------|
| Product | `external_id` | Shopify import dedup |
| Product | `status` | Pending/processing queue queries |
| Classification | `status` | Review list filtering |
| Category | `full_path` | Search and lookup |

## Regression Tests

Query count regression tests in `classification/tests/test_query_performance.py` use `assertNumQueries` to guard against N+1 regressions:

- **`ReviewListQueryCountTest`** — review list must use <= 5 queries
- **`CandidateFinderQueryCountTest`** — cached candidate finder must use 0 DB queries
- **`TaxonomyCacheInvalidationTest`** — cache invalidation and repopulation verified

Concurrency tests in `classification/tests/test_concurrency.py` verify:
- All products in a batch are processed
- Partial failures don't block other products
- Max retries permanently fails products
- `CLASSIFICATION_CONCURRENCY_LIMIT` setting is available
