# Shopify Product Classifier

**Version: v1.0.0** | **Status: Production Ready**

A Django backend that classifies Shopify products into a taxonomy using a two-stage pipeline: a keyword-overlap narrowing step selects candidate categories, then an LLM (Anthropic Claude) picks the best match and extracts product attributes. Results are stored in the database and surfaced through a REST API for human review.

## Table of Contents

- [Architecture](#architecture)
- [Local Setup](#local-setup)
- [Running Tests](#running-tests)
- [Loading Taxonomy Data](#loading-taxonomy-data)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Additional Documentation](#additional-documentation)

## Architecture

The system is a Django REST Framework backend with a Celery task queue for async classification. Products are uploaded via CSV/XLSX import, classified through a multi-step pipeline (candidate narrowing → LLM classification → confidence adjustment → persistence), and results are reviewed by humans through the API.

The classification pipeline runs inside Celery workers using a thread pool for concurrent processing. A taxonomy cache (LocMem in dev, Redis in production) avoids repeated database hits during candidate scoring.

For a detailed description of the high-level and low-level architecture, see [docs/architecture.md](docs/architecture.md).

## Local Setup

### Prerequisites

- Python 3.11+
- Redis (for Celery broker; install via package manager or use Docker)

> **Note:** The dev configuration uses SQLite by default (no database server needed). Production uses MariaDB/MySQL. See [docs/decisions.md](docs/decisions.md) for rationale.

### 1. Clone and create virtual environment

```bash
git clone <repo-url> && cd shopify-product-classifier
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — the only required value for local dev is ANTHROPIC_API_KEY
```

### 4. Start Redis

```bash
# Option A: Docker (recommended)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Option B: System package
# sudo apt install redis-server && sudo systemctl start redis
```

### 5. Run migrations and load taxonomy

```bash
python manage.py migrate
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json
```

### 6. Create a superuser (for admin access and token auth)

```bash
python manage.py createsuperuser
```

### 7. Start the backend server

```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000/admin/` to access the Django admin.

### 8. Start the Celery worker

In a separate terminal:

```bash
source .venv/bin/activate
celery -A config worker --loglevel=info
```

The Celery worker is required for background classification. Without it, uploaded products will stay in "pending" status.

### 9. (Optional) Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:5173` by default.

### 10. (Optional) Start Celery Beat (for stuck-product recovery)

In another separate terminal:

```bash
source .venv/bin/activate
celery -A config beat --loglevel=info
```

This runs the scheduled task that automatically requeues products stuck in "processing" for more than 30 minutes. See [docs/runbook.md](docs/runbook.md) for details.

## Running Tests

```bash
# Run the full test suite
python manage.py test

# Run with coverage (must be ≥90% on classification/, products/, core/)
coverage run --source=classification,products,core,config -m django test
coverage report

# Run a specific module
python manage.py test classification.tests.test_classifier
```

### CI Checks

Every push and pull request runs:
- **Tests** with coverage (must be ≥90% on `classification/`, `products/`, `core/`)
- **Linting** — `black`, `isort`, and `ruff` must pass

CI uses SQLite for the database, so no external services are required.

## Loading Taxonomy Data

The `load_taxonomy` management command ingests Shopify's product taxonomy into the database.

```bash
# Load from local JSON file
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json

# Dry run (preview without writing)
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json --dry-run

# Load from a URL
python manage.py load_taxonomy --source https://example.com/taxonomy.json
```

The command is idempotent — running it multiple times will not create duplicates. It also invalidates the taxonomy cache after a successful load.

### Input JSON format

```json
{
  "categories": [
    { "id": "abc", "name": "Furniture", "parent": null, "attributes": [] },
    { "id": "def", "name": "Sofas", "parent": "abc", "attributes": ["color", "material"] }
  ],
  "attributes": [
    { "id": "xyz", "name": "Color", "handle": "color", "values": ["Red", "Blue"] }
  ]
}
```

## API Reference

All endpoints are documented in detail in [docs/api.md](docs/api.md). Here's a quick reference:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/health/` | No | Health check (DB + Redis) |
| `POST` | `/api/auth/login/` | No | Login, returns auth token |
| `POST` | `/api/products/import/` | Yes | Upload CSV/XLSX, triggers classification |
| `GET` | `/api/products/import/<id>/` | Yes | Check import status |
| `GET` | `/api/taxonomy/categories/` | No | Search taxonomy categories |
| `GET` | `/api/classification/jobs/status/` | No | Dashboard: product counts by status |
| `GET` | `/api/classification/review/` | Yes | List classifications needing review |
| `GET` | `/api/classification/review/<id>/` | Yes | Get single classification |
| `POST` | `/api/classification/review/<id>/approve/` | Yes | Approve a classification |
| `POST` | `/api/classification/review/<id>/correct/` | Yes | Correct a classification |

## Configuration

All environment variables are listed in [`.env.example`](.env.example). Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key for LLM classification |
| `DJANGO_SECRET_KEY` | `insecure-dev-key-change-me` | Django secret key (required in production) |
| `DJANGO_ENV` | `dev` | Set to `prod` for production settings |
| `CLASSIFICATION_CANDIDATE_LIMIT` | `15` | Max candidate categories passed to the LLM |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | `70` | Above this → product "done"; below → "needs_review" |
| `CLASSIFICATION_MAX_RETRIES` | `3` | Per-product retries before permanent failure |
| `CLASSIFICATION_CONCURRENCY_LIMIT` | `5` | Thread pool workers per Celery batch task |
| `TAXONOMY_CACHE_TTL` | `3600` | Taxonomy cache TTL in seconds |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis URL for Celery broker |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated allowed CORS origins |

## Troubleshooting

### "No module named MySQLdb" or database errors

The dev configuration uses SQLite (no install needed). If you see MySQL errors, your `DJANGO_ENV` may be set to `prod`. Either unset it or set `DJANGO_ENV=dev`.

### Celery worker won't start

- Ensure Redis is running: `redis-cli ping` should return `PONG`.
- Check `CELERY_BROKER_URL` in your `.env` matches your Redis instance.

### Products stuck in "processing"

Products can get stuck if the Celery worker crashes. See [docs/runbook.md](docs/runbook.md) for automatic recovery and manual intervention steps.

### AI classification fails with "ANTHROPIC_API_KEY not set"

Add your Anthropic API key to `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### CORS errors from the frontend

Ensure `CORS_ALLOWED_ORIGINS` in `.env` includes your frontend URL (default: `http://localhost:5173`).

### Upload rejected with "Unsupported file type"

Only `.csv` and `.xlsx` files are accepted. Check the file extension and content type.

## Additional Documentation

- [docs/architecture.md](docs/architecture.md) — High-level and low-level system architecture
- [docs/api.md](docs/api.md) — Full API reference with request/response shapes and curl examples
- [docs/runbook.md](docs/runbook.md) — Operational runbook for batch recovery and stuck products
- [docs/security.md](docs/security.md) — Security audit, rate limiting, and production hardening
- [docs/performance.md](docs/performance.md) — Query optimization, caching, and concurrency tuning
- [docs/decisions.md](docs/decisions.md) — Architecture Decision Records with rationale
