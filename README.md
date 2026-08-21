# Shopify Product Classifier

A Django backend that classifies Shopify products into a taxonomy using a two-stage pipeline: keyword-overlap narrowing selects candidate categories, then an LLM (Google Gemini) picks the best match and extracts product attributes. Results are reviewed by humans through a REST API.

## Local Setup

### Prerequisites

- Python 3.11+
- Redis (for Celery broker)

### 1. Clone and set up

```bash
git clone <repo-url> && cd shopify-product-classifier
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — only GEMINI_API_KEY is required for classification
```

### 3. Start Redis

```bash
# Option A: Docker (recommended)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Option B: System package
# sudo apt install redis-server && sudo systemctl start redis
```

### 4. Initialize the database

```bash
python manage.py migrate
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json
python manage.py createsuperuser  # optional, for admin access
```

### 5. Start the backend

```bash
python manage.py runserver
```

### 6. Start the Celery worker

In a separate terminal:

```bash
source .venv/bin/activate
celery -A config worker --loglevel=info
```

### 7. (Optional) Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:5173`.

## Running Tests

```bash
python manage.py test
```

## Docker Compose (alternative)

```bash
docker compose up
```

This starts Redis, the Django server, and the Celery worker.

## Loading Taxonomy Data

```bash
# Load from local JSON file
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json

# Dry run (preview without writing)
python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json --dry-run
```

The command is idempotent and invalidates the taxonomy cache after a successful load.

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

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health/` | Health check |
| `POST` | `/api/products/import/` | Upload CSV/XLSX, triggers classification |
| `GET` | `/api/products/import/<id>/` | Check import status |
| `GET` | `/api/taxonomy/categories/` | Search taxonomy categories |
| `GET` | `/api/classification/jobs/status/` | Product counts by status |
| `GET` | `/api/classification/review/` | List classifications needing review |
| `GET` | `/api/classification/review/<id>/` | Get single classification |
| `POST` | `/api/classification/review/<id>/approve/` | Approve a classification |
| `POST` | `/api/classification/review/<id>/correct/` | Correct a classification |

### Import (POST /api/products/import/)

```bash
curl -X POST http://localhost:8000/api/products/import/ \
  -F "file=@products.csv"
```

CSV columns: `title` (required), `description`, `brand`, `product_type`, `image_urls` (comma- or pipe-separated).

### Review List (GET /api/classification/review/)

```bash
# With filters
curl "http://localhost:8000/api/classification/review/?min_confidence=50&search=t-shirt"
```

### Approve (POST /api/classification/review/\<id\>/approve/)

```bash
curl -X POST http://localhost:8000/api/classification/review/1/approve/
```

### Correct (POST /api/classification/review/\<id\>/correct/)

```bash
curl -X POST http://localhost:8000/api/classification/review/1/correct/ \
  -H "Content-Type: application/json" \
  -d '{"category_id": 58, "attributes": [{"name": "Color", "value": "Red"}]}'
```

## Configuration

Key environment variables (see `.env.example` for all):

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | (required) | API key for LLM classification |
| `AI_MODEL_NAME` | `gemini-3.5-flash-lite` | Model used for classification |
| `AI_RATE_LIMIT_RPM` | `15` | Client-side requests/minute cap (0 disables). Gemini free tier = 15 for flash-lite models |
| `AI_RETRY_MAX_ATTEMPTS` | `3` | Retry attempts per AI call on 5xx/429/timeouts |
| `AI_RETRY_BASE_DELAY` | `2.0` | Base seconds for exponential backoff between retries |
| `DJANGO_SECRET_KEY` | `insecure-dev-key-change-me` | Django secret key |
| `CLASSIFICATION_CANDIDATE_LIMIT` | `15` | Max candidate categories for LLM |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | `70` | Above → "done"; below → "needs_review" |
| `CLASSIFICATION_CONCURRENCY_LIMIT` | `5` | Thread pool workers per batch |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis URL for Celery |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Allowed CORS origins |

## Troubleshooting

**Celery worker won't start:** Ensure Redis is running (`redis-cli ping` → `PONG`).

**Products stuck in "processing":** Run `python manage.py requeue_stuck_products` to reset them to pending.

**"GEMINI_API_KEY not set":** Add your key to `.env`.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — High-level design, data model, pipeline details, and key decisions
