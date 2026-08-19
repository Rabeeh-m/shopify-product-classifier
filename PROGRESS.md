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

# Stage 16: DONE

Documentation consolidation — README rewrite, architecture docs, API reference, decisions log, env var audit, service docstrings.

## Changes

### README.md (rewrite)
- Complete rewrite as single entry point for new developers
- Added table of contents with cross-links to all docs
- Architecture summary paragraph with link to docs/architecture.md
- Step-by-step local setup (10 steps, correct order: venv → deps → env → Redis → migrate → taxonomy → superuser → server → worker → optional frontend/beat)
- Accurate for dev settings (SQLite, no MariaDB needed locally)
- Configuration table with all key env vars
- Troubleshooting section covering the most common setup issues
- API quick-reference table

### docs/architecture.md (new)
- High-level component diagram (Django, Celery, Redis, Anthropic, DB)
- Data flow diagram from import through classification to persistence
- Low-level architecture: Django apps, Celery config, taxonomy caching, settings structure, key models
- Classification pipeline services described in sequence

### docs/api.md (new)
- All 10 endpoints documented from actual DRF views/serializers
- Method, path, auth requirement, request/response shape for each
- Working curl examples for every endpoint
- Rate limiting, authentication, and pagination sections
- Error format documented

### docs/decisions.md (new)
- 6 Architecture Decision Records: MariaDB over Postgres, Celery+Redis, two-stage pipeline, thread pool concurrency, taxonomy caching, SQLite in dev

### .env.example (audit)
- Added 8 missing env vars: CLASSIFICATION_CANDIDATE_LIMIT, CLASSIFICATION_CONFIDENCE_THRESHOLD, CLASSIFICATION_MAX_RETRIES, CLASSIFICATION_CONCURRENCY_LIMIT, TAXONOMY_CACHE_TTL, SECURE_HSTS_SECONDS, SECURE_SSL_REDIRECT, REDIS_URL
- Removed stale MEDIA_ROOT (not referenced via os.environ)
- Added commented-out prod-only section for SECURE_HSTS_SECONDS, SECURE_SSL_REDIRECT, REDIS_URL

### docs/runbook.md (consolidation)
- Added cross-reference header linking to README, security, API, architecture

### docs/security.md (consolidation)
- Added cross-reference header linking to README, runbook, API, architecture

### Service Docstrings
- `products/services/import_service.py` — added docstrings to ParseError, import_products, _normalize_header, _read_csv, _read_xlsx, _parse_image_urls, _validate_headers, _create_products
- `classification/services/review_service.py` — added docstring to ReviewError
- `classification/services/candidate_finder.py` — added docstring to CandidateResult
- `taxonomy/services/cache.py` — added docstring to get_ttl

## Verification
- All 254 tests pass, 0 failures
- ruff, black, isort all pass on modified files
- All 24 env vars from codebase accounted for in .env.example
- No stale env vars in .env.example

## Files Created
- `docs/architecture.md`
- `docs/api.md`
- `docs/decisions.md`

## Files Modified
- `README.md` (full rewrite)
- `.env.example` (audit/complete)
- `docs/runbook.md` (cross-reference header)
- `docs/security.md` (cross-reference header)
- `products/services/import_service.py` (docstrings)
- `classification/services/review_service.py` (docstring)
- `classification/services/candidate_finder.py` (docstring)
- `taxonomy/services/cache.py` (docstring)

## Test Status
- 254 tests, 0 failures

---

# Stage 17: NEXT
