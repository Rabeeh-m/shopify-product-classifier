# Shopify Product Classifier

Upload a product CSV/XLSX and every product is automatically classified into a
Shopify-style category taxonomy using the Gemini AI model. A React UI lets you
upload files, watch live progress, review low-confidence results, and browse
everything that was classified.

No external services required — just Python + SQLite on the backend and Node on
the frontend.

## Quick start

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # set GEMINI_API_KEY inside
python manage.py migrate
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json
python manage.py runserver    # http://localhost:8000

# Frontend (new terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## How it works

1. **Upload** — the app accepts a CSV or XLSX file and parses it into products.
2. **Classify** — each product is matched to a category, in two passes:
   - **Pass 1 (rules):** exact vendor sub-category matches are applied instantly,
     with no AI call. If a mapped category is missing, the product falls through
     to AI instead of failing.
   - **Pass 2 (AI):** everything else is sent to Gemini in parallel (up to 5
     workers) with rate limiting and retries. One bad row never blocks the batch.
3. **Review** — each result gets a **confidence score**. Scores below the
   auto-approve threshold wait in the review queue for a human.
4. **Browse** — see the classified products, or open any product to view its
   full details.

- **Confidence** — the AI's self-reported score is adjusted for missing data
  (title-only caps at 50, no description at 65, no image −5). Scores ≥ 70 are
  auto-approved; the rest wait in the review queue. Products list and review
  queue show a circular indicator colored green / yellow / red by score.
- **Review** — approve as-is, or correct the category and attributes.
  Low-confidence items also show the AI's alternative suggestions for context.
- **Product detail page** — click any product card to open its page with the
  image gallery, category, attributes, source data, confidence, and status.
- **Re-run** — `python manage.py classify_products [--import-id <id>]` retries
  anything not yet classified (pending, processing, or failed). Let one run
  finish before starting another.
- **Resumable UI** — leaving and re-opening the Upload page restores the last
  import's progress and keeps polling while work is still running.

## Architecture

A single Django process + a single React SPA. No Celery/Redis/workers — heavy
work runs on a background thread inside the web process.

```
┌────────────────────────── Browser ──────────────────────────┐
│  React SPA (Vite)                                           │
│  UploadPage · ProductsPage · ProductDetailPage · ReviewPage │
└──────────────────────────┬──────────────────────────────────┘
                           │ fetch() → /api/* (proxied in dev)
┌──────────────────────────▼──────────────────────────────────┐
│  Django + DRF                                               │
│                                                             │
│  products/         upload API · CSV/XLSX parsing            │
│  taxonomy/         category & attribute store · in-memory   │
│                    cache (TTL 1h)                           │
│  classification/                                            │
│    views.py        review queue · browse · product detail   │
│                    · job status                             │
│    tasks.py        background pipeline                      │
│      PASS 1  rules.py     vendor dict → leaf (no AI)        │
│      PASS 2  classifier.py → ai_client.py (Gemini)          │
│              shared RateLimiter · retries w/ backoff        │
│    persistence.py  saves results, auto-approve ≥ threshold  │
└──────────────────────────┬──────────────────────────────────┘
                           │ ORM
                  ┌────────▼────────┐        ┌──────────────┐
                  │    SQLite       │        │ Gemini API   │
                  │ products,       │        │ (HTTPS only, │
                  │ imports,        │        │  no SDK      │
                  │ categories,     │        │  state)      │
                  │ classifications │        └──────────────┘
                  └─────────────────┘
```

Key decisions:

- **One code path for import** — the HTTP view stores the file, then the same
  `import_products()` + `process_products()` pipeline runs on a daemon thread;
  tests call those functions directly.
- **Rules before AI** — exact-match vendor sub-categories cost zero AI calls;
  only misses reach Gemini. Missing taxonomy leaves also fall through to AI.
- **Shared rate limiting** — all worker threads draw from one sliding-window
  limiter (`AI_RATE_LIMIT_RPM`), so parallelism never exceeds the provider's
  per-minute quota.
- **Failure isolation** — each product is classified independently; one bad row
  becomes a stored error, never a crashed batch.
- **Everything reviewable** — low-confidence results land in a review queue;
  human corrections always win over machine output.

## Project layout

```
products/          Product & ProductImport models, upload API, file parsing
taxonomy/          Category & attribute models, load_taxonomy command
classification/    Rules dict, Gemini client, persistence, background pipeline,
                   review API, product detail API
frontend/src/      React SPA: UploadPage · ProductsPage · ProductDetailPage · ReviewPage
```

## API

| Method | Endpoint                                   | Purpose                              |
| ------ | ------------------------------------------ | ------------------------------------ |
| POST   | `/api/products/import/`                    | Upload CSV/XLSX                      |
| GET    | `/api/products/import/latest/`             | Most recent import (UI restore)      |
| GET    | `/api/products/import/<id>/`               | Import progress/status               |
| DELETE | `/api/products/clear/`                     | Wipe all products & imports          |
| GET    | `/api/classification/jobs/status/`         | Pending/processing/done counts       |
| GET    | `/api/classification/products/`            | Browse (search, filters, paging)     |
| GET    | `/api/classification/products/<id>/`       | Full product + classification detail |
| GET    | `/api/classification/review/`              | Review queue list                    |
| POST   | `/api/classification/review/<id>/approve/` | Approve as-is                        |
| POST   | `/api/classification/review/<id>/correct/` | Correct category/attributes          |
| GET    | `/api/taxonomy/categories/?q=`             | Category search                      |

Main settings live in `.env` (see `.env.example`): `GEMINI_API_KEY`,
`AI_MODEL_NAME`, `AI_RATE_LIMIT_RPM`,
`CLASSIFICATION_CONFIDENCE_THRESHOLD`, `CLASSIFICATION_CONCURRENCY_LIMIT`.

Tips:

- If the Gemini free-tier daily quota is hit, products fail with a stored error
  — re-run `classify_products` after the quota resets (or switch `AI_MODEL_NAME`)
  and they will be retried.
- If you edit the taxonomy JSON, reload it with `load_taxonomy` and restart the
  server so its in-memory cache refreshes.

## Tests

```bash
.venv/bin/python manage.py test     # backend (176 tests)
cd frontend && npm test             # frontend (14 tests)
```
