# Stage 15: DONE

Performance optimization — N+1 query fixes, taxonomy caching, concurrency tuning, query count regression tests.

## Changes

### N+1 Query Fix — Review List (`classification/views.py`, `classification/serializers.py`)
- View now bulk-loads all unique alternative category IDs for the entire page in one query
- `CategoryCache` shared via DRF context dict across all serializer instances
- `AlternativeSerializer.get_category()` checks the context cache before hitting DB
- **Result:** 29 queries → 5 queries (83% reduction) for a 25-item page

### Taxonomy Caching (`taxonomy/services/cache.py`)
- Created `get_all_categories()` — Redis-backed (prod) / LocMem (dev) cache with configurable TTL
- `invalidate_taxonomy_cache()` — explicit invalidation called by `load_taxonomy` after successful non-dry-run load
- Candidate finder now uses cached taxonomy: 10 DB queries → 0 (after warm)
- `TAXONOMY_CACHE_TTL` setting (default 3600s)

### Candidate Finder (`classification/services/candidate_finder.py`)
- Removed direct `Category.objects.all()` query — now imports `get_all_categories()` from cache module
- Accepts pre-loaded categories list to skip even the cache lookup
- Zero DB queries when taxonomy cache is warm

### Concurrency Tuning (`classification/tasks.py`)
- Added `CLASSIFICATION_CONCURRENCY_LIMIT` setting (env var, default 5)
- `process_product_batch` ThreadPoolExecutor now uses this limit instead of hardcoded `_MAX_WORKERS=5`
- Failed product status updates now use `bulk_update()` instead of per-product `save()` — fewer DB round-trips

### Database Index (`classification/models.py`, `classification/migrations/0003_...`)
- Added composite index `idx_cls_status_created` on `(status, -created_at)` for review list query pattern

### CACHES Configuration
- `config/settings/base.py`: LocMemCache default
- `config/settings/prod.py`: Redis-backed cache via `REDIS_URL` env var

### Settings
- `CLASSIFICATION_CONCURRENCY_LIMIT` (env var, default 5)
- `TAXONOMY_CACHE_TTL` (env var, default 3600)
- `CACHES` dict added to base + prod settings

### Performance Tests (`classification/tests/test_query_performance.py`)
- `ReviewListQueryCountTest` — assertNumQueries(5) for 25-item review list
- `CandidateFinderQueryCountTest` — assertNumQueries(0) for cached candidate lookup
- `TaxonomyCacheInvalidationTest` — cache invalidation + repopulation verified

### Concurrency Tests (`classification/tests/test_concurrency.py`)
- `test_all_products_processed` — all 5 products in batch processed
- `test_partial_failure_doesnt_block_others` — 1 failure doesn't block other 4
- `test_max_retries_permanent_failure` — product with retry_count=3 stays failed
- `test_concurrency_limit_setting_exists` — setting is available

### Documentation
- Created `docs/performance.md` with before/after numbers, caching architecture, concurrency tuning guide

## Files Created
- `taxonomy/services/__init__.py`
- `taxonomy/services/cache.py`
- `classification/tests/test_query_performance.py`
- `classification/tests/test_concurrency.py`
- `classification/migrations/0003_add_status_created_at_index.py`
- `docs/performance.md`

## Files Modified
- `classification/serializers.py` — N+1 fix: bulk-load alternative categories, context cache sharing
- `classification/views.py` — pre-compute alternative category cache per page
- `classification/services/candidate_finder.py` — use taxonomy cache instead of per-call DB query
- `classification/tasks.py` — concurrency limit setting, bulk error handling, bulk_update
- `classification/models.py` — composite index on (status, -created_at)
- `taxonomy/management/commands/load_taxonomy.py` — invalidate cache after successful load
- `config/settings/base.py` — CACHES, CLASSIFICATION_CONCURRENCY_LIMIT, TAXONOMY_CACHE_TTL
- `config/settings/prod.py` — Redis-backed CACHES
- `profile_stage15.py` — profiling script (updated for post-optimization verification)

## Test Status
- 254 tests, 0 failures
- New tests added: 8 (4 query performance + 4 concurrency)

---

# Stage 16: NEXT
