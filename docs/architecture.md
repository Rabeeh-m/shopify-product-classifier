# Architecture

## High-Level Overview

The Shopify Product Classifier is a Django REST Framework backend with a Celery task queue for asynchronous product classification. It follows a pipeline architecture: products enter through a file import, get classified by an LLM against a Shopify taxonomy, and results are surfaced through a review API for human validation.

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Frontend   │────▶│  Django API  │────▶│   MariaDB   │
│  (React/    │     │  (DRF)       │     │  (prod)     │
│   Vite)     │     └──────┬───────┘     │  SQLite     │
└─────────────┘            │              │  (dev)      │
                           │              └─────────────┘
                           ▼
                    ┌──────────────┐     ┌─────────────┐
                    │    Celery    │────▶│    Redis     │
                    │   Worker     │     │  (broker +   │
                    │  (thread     │     │   cache)     │
                    │   pool)      │     └─────────────┘
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   Anthropic   │
                    │   Claude API  │
                    └──────────────┘
```

**Components:**
- **Django REST Framework** — REST API for product import, classification review, taxonomy search, and health checks. Auth via DRF tokens.
- **Celery worker** — Processes classification asynchronously. Uses a thread pool (configurable concurrency) to classify multiple products concurrently within a single batch task.
- **Redis** — Serves as the Celery message broker and (in production) the Django cache backend for taxonomy caching.
- **Anthropic Claude** — The LLM used for the classification step. Called via the `anthropic` Python SDK with built-in retry logic.
- **Database** — SQLite in development, MariaDB/MySQL in production. Stores products, classifications, taxonomy categories, and Celery task results.

## Data Flow

```
CSV/XLSX Upload
       │
       ▼
  import_service.import_products()
  → Creates Product (status=pending) + ProductImage rows
       │
       ▼  (triggered via API or management command)
  process_all_pending (Celery task, self-re-enqueuing loop)
       │
       ▼
  process_product_batch (Celery task, thread pool)
       │
       ├── _mark_processing (status=processing)
       │
       ├── Per product (thread pool):
       │      │
       │      ▼
       │    find_candidates()  — keyword-overlap scoring, returns top N
       │      │
       │      ▼
       │    classify_product() — builds prompt, calls Claude, parses JSON
       │      │
       │      ▼
       │    calculate_confidence() — adjusts for data completeness
       │      │
       │      ▼
       │    save_classification() — atomic DB write
       │
       └── Per-product error handling:
              - On failure: retry_count++ → requeue or permanent FAILED
              - On success: processing_started_at cleared
```

## Low-Level Architecture

### Django Apps

| App | Purpose |
|-----|---------|
| `core` | Health check endpoint |
| `taxonomy` | Shopify category/attribute models, search API, cache layer |
| `products` | Product and ProductImport models, CSV/XLSX import service |
| `classification` | Classification models, review API, AI classification pipeline |

### Classification Pipeline Services

All classification logic is decomposed into single-responsibility service modules under `classification/services/`. They are composed only in `classification/tasks.py` — `_run_pipeline()` calls them in sequence:

1. **`candidate_finder.py`** — Tokenizes product text fields, scores every taxonomy category via keyword overlap (name match = 3 pts, path match = 1 pt, both = +0.5 bonus), returns the top N candidates. Uses taxonomy cache to avoid per-product DB queries. Designed as an extension point for future embedding-based search.

2. **`classifier.py`** — Builds a structured prompt with product info and candidate categories, sends it to Claude via `ai_client.py`, and validates the JSON response. Rejects any `chosen_category_id` not in the candidate set to prevent hallucinated categories.

3. **`confidence.py`** — Pure function that adjusts the AI's self-reported confidence based on data completeness. Rules (mutually exclusive, first-match wins): title-only capped at 50, no-description capped at 65, no-image gets 5-point penalty (floor 30), all-data-present passes through unchanged.

4. **`persistence.py`** — Saves the classification result in one atomic transaction: updates/creates the `Classification` row, replaces `ClassificationAttribute` rows, and mirrors status onto the `Product`. Auto-creates taxonomy attributes if the AI invents new ones.

5. **`ai_client.py`** — Wraps the Anthropic SDK. Implements internal retry logic (3 attempts) for timeouts, 5xx errors, and 429 rate limits. Logs latency and token usage on every call.

6. **`review_service.py`** — Handles human review actions (approve/correct). Validates that corrections reference valid taxonomy attributes for the target category. Generates human-readable correction notes.

### Celery Configuration

- **Broker:** Redis (`CELERY_BROKER_URL`, default `redis://localhost:6379/0`)
- **Result backend:** Django DB (`django-celery-results`)
- **Tasks:**
  - `process_all_pending` — Self-re-enqueuing loop: fetches pending products in chunks, dispatches `process_product_batch`, re-enqueues itself if more remain
  - `process_product_batch` — Processes a batch of product IDs concurrently via `ThreadPoolExecutor` (capped at `CLASSIFICATION_CONCURRENCY_LIMIT`, default 5)
  - `requeue_stuck_products_task` — Celery Beat task (every 15 min) that resets products stuck in "processing" for >30 minutes

Two-tier retry system: Celery retries the task itself (max 2 retries), and each product has its own `retry_count` (max `CLASSIFICATION_MAX_RETRIES`, default 3) before permanent failure.

### Taxonomy Caching

`taxonomy/services/cache.py` provides `get_all_categories()` which loads the full taxonomy from Django's cache framework. In development this uses LocMemCache; in production it uses Redis with a configurable TTL (`TAXONOMY_CACHE_TTL`, default 3600s). The cache is invalidated after a successful `load_taxonomy` management command run.

### Settings Structure

- `config/settings/base.py` — All shared settings, env var loading via `python-dotenv`
- `config/settings/dev.py` — Overrides database to SQLite, enables debug toolbar
- `config/settings/prod.py` — Security hardening (HSTS, SSL redirect, secure cookies), Redis cache, required `DJANGO_SECRET_KEY`
- `config/settings/__init__.py` — Selects dev or prod based on `DJANGO_ENV` env var

### Key Models

| Model | App | Purpose |
|-------|-----|---------|
| `Category` | taxonomy | Taxonomy category with hierarchical `full_path` |
| `Attribute` | taxonomy | Taxonomy attribute (e.g., "Color", "Material") |
| `AttributeValue` | taxonomy | Predefined value for an attribute |
| `Product` | products | Imported product with status tracking |
| `ProductImage` | products | Product image URLs |
| `ProductImport` | products | Import job metadata and status |
| `Classification` | classification | AI classification result per product |
| `ClassificationAttribute` | classification | Extracted attributes for a classification |
