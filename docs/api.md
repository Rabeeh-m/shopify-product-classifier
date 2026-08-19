# API Reference

Base URL: `http://localhost:8000` (development)

All responses use JSON. All endpoints are open (no authentication required).

## Rate Limiting

Global DRF throttles apply to all endpoints: anonymous 60/min. Review write endpoints (approve/correct) are limited to 30/min.

When throttled, the response is HTTP 429 with:
```json
{
  "error": {
    "code": "THROTTLED",
    "message": "Request was throttled..."
  }
}
```

## Error Format

All error responses use a consistent shape:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description"
  }
}
```

---

## 1. Health Check

```
GET /api/health/
```

**Auth required:** No

**Response (200 — healthy):**
```json
{
  "status": "healthy",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

**Response (503 — degraded):**
```json
{
  "status": "degraded",
  "checks": {
    "database": "ok",
    "redis": "fail"
  }
}
```

**Response header:** `X-Health-Status: healthy` or `X-Health-Status: degraded`

```bash
curl http://localhost:8000/api/health/
```

---

## 2. Product Import (Create)

```
POST /api/products/import/
```

**Content-Type:** `multipart/form-data`

**Form field:** `file` — a `.csv` or `.xlsx` file.

CSV columns: `title` (required), `description`, `brand`, `product_type`, `image_urls` (optional). Image URLs can be comma- or pipe-separated.

**Response (201):**
```json
{
  "id": 1,
  "file": "/imports/products.csv",
  "status": "completed",
  "total_rows": 150,
  "imported_rows": 148,
  "failed_rows": 2,
  "error_log": [
    {"row": 5, "error": "Missing required field: title"},
    {"row": 42, "error": "Missing required field: title"}
  ],
  "created_at": "2026-08-19T12:00:00Z",
  "completed_at": "2026-08-19T12:00:05Z"
}
```

**Response (400 — no file):**
```json
{
  "error": {
    "code": "ERROR",
    "message": "No file provided. Send a file as 'file'."
  }
}
```

**Response (400 — parse error):**
```json
{
  "errors": ["Missing required column(s): title"]
}
```

After a successful import, the Celery task `process_all_pending` is automatically triggered to classify the new products.

```bash
curl -X POST http://localhost:8000/api/products/import/ \
  -F "file=@products.csv"
```

---

## 3. Product Import (Detail)

```
GET /api/products/import/<id>/
```

**Response (200):** Same shape as the create response, with current import status.

**Response (404):**
```json
{
  "error": {
    "code": "ERROR",
    "message": "Import not found."
  }
}
```

```bash
curl http://localhost:8000/api/products/import/1/
```

---

## 4. Category Search

```
GET /api/taxonomy/categories/?search=<query>
```

**Auth required:** No

**Query parameters:**
- `search` (optional) — case-insensitive substring filter on `full_path`

Returns up to 20 results, ordered by `full_path`.

**Response (200):**
```json
[
  {
    "id": 42,
    "name": "T-Shirts",
    "full_path": "Clothing > Tops > T-Shirts"
  },
  {
    "id": 58,
    "name": "Tank Tops",
    "full_path": "Clothing > Tops > Tank Tops"
  }
]
```

```bash
curl "http://localhost:8000/api/taxonomy/categories/?search=t-shirt"
```

---

## 5. Classification Job Status

```
GET /api/classification/jobs/status/
```

**Auth required:** No

**Response (200):**
```json
{
  "total": 1500,
  "pending": 100,
  "processing": 50,
  "done": 1200,
  "needs_review": 100,
  "failed": 50
}
```

```bash
curl http://localhost:8000/api/classification/jobs/status/
```

---

## 6. Review List

```
GET /api/classification/review/
```

**Query parameters (all optional):**
- `min_confidence` — filter: confidence >= value
- `max_confidence` — filter: confidence <= value
- `search` — case-insensitive substring match on product title
- `page` — page number (25 items per page)

**Response (200, paginated):**
```json
{
  "count": 100,
  "next": "http://localhost:8000/api/classification/review/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "product": {
        "id": 1,
        "title": "Classic Cotton T-Shirt",
        "image_urls": [
          "http://localhost:8000/media/products/img1.jpg"
        ]
      },
      "category": {
        "id": 42,
        "name": "T-Shirts",
        "full_path": "Clothing > Tops > T-Shirts"
      },
      "alternatives": [
        {
          "category_id": 58,
          "category": {
            "id": 58,
            "name": "Tank Tops",
            "full_path": "Clothing > Tops > Tank Tops"
          },
          "confidence": 75.0
        }
      ],
      "attributes": [
        {
          "attribute_name": "Color",
          "value_display": "Blue",
          "free_text_value": ""
        }
      ],
      "confidence": 92.0,
      "status": "needs_review",
      "reviewed_by": null,
      "reviewed_at": null,
      "correction_notes": "",
      "created_at": "2026-08-19T10:00:00Z",
      "updated_at": "2026-08-19T10:00:00Z"
    }
  ]
}
```

```bash
curl http://localhost:8000/api/classification/review/

# With filters
curl "http://localhost:8000/api/classification/review/?min_confidence=50&search=t-shirt"
```

---

## 7. Review Detail

```
GET /api/classification/review/<id>/
```

**Response (200):** Single classification object with the same shape as items in the review list `results` array.

**Response (404):**
```json
{
  "error": "Classification not found"
}
```

```bash
curl http://localhost:8000/api/classification/review/1/
```

---

## 8. Approve Classification

```
POST /api/classification/review/<id>/approve/
```

**Throttle:** 30 requests/minute  
**Request body:** None (empty POST)

Approves a classification in `needs_review` status. Sets the classification status to `approved`, records the reviewer and timestamp, and sets the product status to `done`.

**Response (200):** Updated classification object (same shape as review detail).

**Response (404):**
```json
{
  "error": "Classification not found"
}
```

**Response (409 — wrong status):**
```json
{
  "error": "Cannot approve classification in status 'approved'"
}
```

```bash
curl -X POST http://localhost:8000/api/classification/review/1/approve/
```

---

## 9. Correct Classification

```
POST /api/classification/review/<id>/correct/
```

**Throttle:** 30 requests/minute

Corrects a classification in `needs_review` status by updating its category and/or attributes.

**Request body:**
```json
{
  "category_id": 42,
  "attributes": [
    {
      "name": "Color",
      "value": "Red"
    }
  ]
}
```

Both `category_id` and `attributes` are optional — supply one or both. If `attributes` is provided (even as an empty array), it replaces all existing attributes.

**Response (200):** Updated classification object (same shape as review detail).

**Response (404):**
```json
{
  "error": "Classification not found"
}
```

**Response (409 — wrong status):**
```json
{
  "error": "Cannot correct classification in status 'approved'"
}
```

**Response (400 — invalid attribute):**
```json
{
  "error": "Attribute 'Foo' is not valid for category 'Clothing > Tops > T-Shirts'"
}
```

```bash
# Change category only
curl -X POST http://localhost:8000/api/classification/review/1/correct/ \
  -H "Content-Type: application/json" \
  -d '{"category_id": 58}'

# Update attributes only
curl -X POST http://localhost:8000/api/classification/review/1/correct/ \
  -H "Content-Type: application/json" \
  -d '{"attributes": [{"name": "Color", "value": "Red"}]}'
```

---

## Pagination

List endpoints use page-number pagination with 25 items per page by default. The paginated response includes `count`, `next`, `previous`, and `results` fields. Use the `?page=N` query parameter to navigate pages.
