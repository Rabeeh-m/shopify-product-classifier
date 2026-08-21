# Architecture

## High-Level Overview

The Shopify Product Classifier is a Django REST Framework backend with a Celery task queue for asynchronous product classification. Products are uploaded via CSV/XLSX import, classified through a two-stage pipeline (keyword-overlap narrowing → LLM classification), and results are reviewed by humans through a REST API.

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Frontend   │────▶│  Django API  │────▶│   SQLite    │
│  (React/    │     │  (DRF)       │     │  (dev)      │
│   Vite)     │     └──────┬───────┘     └─────────────┘
└─────────────┘            │
                           ▼
                    ┌──────────────┐     ┌─────────────┐
                    │    Celery    │────▶│    Redis     │
                    │   Worker     │     │  (broker +   │
                    │  (thread     │     │   cache)     │
                    │   pool)      │     └─────────────┘
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Google AI   │
                    │  Gemini API  │
                    └──────────────┘
```

## Data Model

```
Category ──┬── parent (self-FK, PROTECT)
           ├── name, full_path, shopify_category_id
           └── category_attributes ──▶ CategoryAttribute ──▶ Attribute
                                                              └── values ──▶ AttributeValue

Product ──── external_id, title, description, brand, product_type, raw_data
  ├── status (pending → processing → done | needs_review | failed)
  ├── error_message, processing_started_at
  ├── images ──▶ ProductImage (url, is_valid)
  └── classification ──▶ Classification (OneToOne)
                          ├── category (FK → Category)
                          ├── confidence, alternatives (JSON)
                          ├── status (needs_review | approved | failed)
                          ├── reviewed_by, reviewed_at, correction_notes
                          └── attributes ──▶ ClassificationAttribute
                                              ├── attribute (FK → Attribute)
                                              ├── value (FK → AttributeValue, nullable)
                                              └── free_text_value

ProductImport ── file, status, total_rows, imported_rows, failed_rows, error_log
```

## Classification Pipeline

The pipeline is composed of five single-responsibility services, called in sequence by `_run_pipeline()` in `classification/tasks.py`:

0. **`rule_classifier.py`** — Attempts vendor import mappings (Product List.xlsx-style sub-categories) and high-confidence keyword auto-pick before any AI call. Returns `None` when ambiguous so the product falls through to Gemini. Controlled by `RULE_CLASSIFICATION_ENABLED` and related settings. The vendor map in `classification/data/vendor_category_rules.py` covers all 20 sub-categories in Product List.xlsx via direct mappings, title-keyword disambiguation rules, and per-sub-category `default` targets; on that sheet it classifies ~96% of rows without any API call.

1. **`candidate_finder.py`** — Tokenizes product text fields (title, description, product_type, brand, key raw_data columns), scores every taxonomy category via keyword overlap (name match = 3 pts, path match = 1 pt, both = +0.5 bonus), returns the top N candidates (default 15). Uses Django's cache framework (LocMem in dev) to avoid repeated DB queries. Designed as an extension point for embedding-based search.

2. **`classifier.py`** — Builds a structured prompt with product info and candidate categories, sends it to Gemini via `ai_client.py`, and validates the JSON response. Rejects any `chosen_category_id` not in the candidate set to prevent hallucinated categories.

3. **`confidence.py`** — Pure function that adjusts the AI's self-reported confidence based on data completeness. Rules (first-match wins): title-only capped at 50, no-description capped at 65, no-image gets 5-point penalty (floor 30), all-data-present passes through unchanged. Applied to AI responses only — rule-layer confidence (vendor mapping strength, keyword score gaps) passes through unadjusted.

4. **`persistence.py`** — Saves the classification result in one atomic transaction: updates/creates the `Classification` row, replaces `ClassificationAttribute` rows, and mirrors status onto the `Product`. Auto-creates taxonomy attributes if the AI invents new ones. Confidence at or above `CLASSIFICATION_CONFIDENCE_THRESHOLD` (default 70) auto-approves the classification (`status=approved`, product `done`) so it never enters the review queue; below the threshold it lands in `needs_review` for a human.

5. **`ai_client.py`** — Wraps the Anthropic SDK. Implements internal retry logic (3 attempts) for timeouts, 5xx errors, and 429 rate limits.

6. **`review_service.py`** — Handles human review actions (approve/correct). Validates that corrections reference valid taxonomy attributes for the target category. Generates human-readable correction notes.

## Async Processing (Celery)

- **Broker:** Redis (`CELERY_BROKER_URL`)
- **Result backend:** Django DB (`django-celery-results`)
- **Tasks:**
  - `process_all_pending` — Fetches all pending products once, chunks them, and queues the batches via a Celery chain so exactly one batch runs at a time (no self re-enqueue, no concurrent batches).
  - `process_product_batch` — Two-phase batch processing. Phase 1 runs the rules fast path inline (no AI, no rate limit, no thread pool) for every product; only rule misses advance to phase 2, which classifies concurrently via `ThreadPoolExecutor` (capped at `CLASSIFICATION_CONCURRENCY_LIMIT`, default 5) against Gemini. A process-wide write lock serializes `save_classification()` calls so concurrent SQLite writers don't thrash.
  - **Sequential dispatch:** both producers (`import_and_classify_products`, `process_all_pending`) queue their batches through `_dispatch_classification_chunks()`, which builds a Celery `chain`. Concurrent batches would multiply the per-process AI rate limiter across worker processes and contend for SQLite write locks; chaining keeps a single batch in flight regardless of worker count. SQLite dev connections additionally run with WAL journal mode and a 60s busy timeout (`DATABASES["OPTIONS"]`).

**Per-product error isolation:** Each product is processed in its own `try/except` via `_run_pipeline_safe()`. A failure on one product (broken image, bad AI response, missing data) doesn't affect others. Failed products are marked `status=failed` with the error message preserved.

**Resumability:** Products track their state via `Product.status`. If a worker crashes mid-batch, stuck products can be recovered with:
```bash
python manage.py requeue_stuck_products
```
This resets products stuck in `processing` for >30 minutes back to `pending`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health/` | Health check (DB connectivity) |
| `POST` | `/api/products/import/` | Upload CSV/XLSX, triggers classification |
| `GET` | `/api/products/import/<id>/` | Check import status |
| `GET` | `/api/taxonomy/categories/` | Search taxonomy categories |
| `GET` | `/api/classification/jobs/status/` | Dashboard: product counts by status |
| `GET` | `/api/classification/review/` | List classifications needing review |
| `GET` | `/api/classification/review/<id>/` | Get single classification |
| `POST` | `/api/classification/review/<id>/approve/` | Approve a classification |
| `POST` | `/api/classification/review/<id>/correct/` | Correct a classification |

All endpoints return a consistent error envelope:
```json
{"error": {"code": "ERROR_CODE", "message": "Human-readable description"}}
```

## Django Apps

| App | Purpose |
|-----|---------|
| `core` | Health check endpoint |
| `taxonomy` | Category/Attribute models, search API, cache layer |
| `products` | Product/ProductImport models, CSV/XLSX import service |
| `classification` | Classification models, review API, AI classification pipeline |

## Key Design Decisions

**Why two-stage narrow-then-classify?** Shopify's taxonomy has thousands of categories. Sending all to an LLM would exceed token limits and degrade accuracy. The keyword-overlap scorer is fast (pure Python, zero DB queries after cache warm) and filters to ~15 candidates. The LLM then makes the final decision from a focused set.

**Why thread pool concurrency inside Celery?** Classification is I/O-bound (LLM API calls). A thread pool within a single Celery task shares one process and DB connection while processing multiple products concurrently. Celery's prefork would spawn separate processes with redundant overhead.

**Why LocMemCache in dev?** Taxonomy data changes rarely and is read on every classification. LocMemCache requires zero setup. The cache is invalidated after successful `load_taxonomy` runs.

**Why SQLite in dev / MariaDB in prod?** SQLite requires no database server — developers can run the full test suite with zero infrastructure. The dev settings override to SQLite automatically.
