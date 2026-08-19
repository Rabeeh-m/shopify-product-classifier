# Security Audit — Shopify Product Classifier

> Cross-references: [README.md](../README.md) | [Runbook](runbook.md) | [API](api.md) | [Architecture](architecture.md)

## Audit Date
Stage 14 — August 2026

## Scope
Full codebase security review covering secrets handling, upload security,
endpoint permissions, rate limiting, production hardening, and external
data-sharing practices.

---

## 1. Secrets & Credentials

| Check | Status |
|---|---|
| No hardcoded API keys or passwords in source | ✅ |
| `DJANGO_SECRET_KEY` read from env, required in prod | ✅ |
| `ANTHROPIC_API_KEY` read from env, fails fast if missing | ✅ |
| DB credentials read from env | ✅ |
| No secrets written to logs | ✅ |
| `.env.example` contains placeholders only | ✅ |

## 2. Upload Security

| Check | Status |
|---|---|
| File extension whitelist (`.csv`, `.xlsx`) | ✅ |
| MIME-type secondary validation | ✅ Added Stage 14 |
| File size limit enforced server-side (`MAX_UPLOAD_SIZE_MB`, default 10 MB) | ✅ |
| Filename sanitised before DB storage | ✅ Added Stage 14 |
| Django `FileField` handles storage path safely | ✅ |

## 3. Authentication & Permissions

| Endpoint | Method | Auth Required | Rate Limit |
|---|---|---|---|
| `/api/auth/login/` | POST | No (AllowAny) | 10/min (LoginThrottle) |
| `/api/health/` | GET | No | Global 60/min anon |
| `/api/classification/jobs/status/` | GET | No | Global 60/min anon |
| `/api/taxonomy/categories/` | GET | No | Global 60/min anon |
| `/api/products/import/` | POST | **Yes** (IsAuthenticated) | Global 120/min user |
| `/api/products/import/<id>/` | GET | **Yes** (IsAuthenticated) | Global 120/min user |
| `/api/classification/review/` | GET | **Yes** (IsAuthenticated) | Global 120/min user |
| `/api/classification/review/<id>/` | GET | **Yes** (IsAuthenticated) | Global 120/min user |
| `/api/classification/review/<id>/approve/` | POST | **Yes** (IsAuthenticated) | 30/min (ReviewWriteThrottle) |
| `/api/classification/review/<id>/correct/` | POST | **Yes** (IsAuthenticated) | 30/min (ReviewWriteThrottle) |

Global DRF throttling: `anon: 60/minute`, `user: 120/minute`.

## 4. Rate Limiting (Throttling)

| Layer | Config | Added |
|---|---|---|
| Global DRF defaults | anon 60/min, user 120/min | Stage 14 |
| Login endpoint | 10/min (LoginThrottle, per-IP) | Stage 14 |
| Review approve/correct | 30/min (ReviewWriteThrottle, per-user) | Stage 14 |
| Exception handler | Returns `{"error": {"code": "THROTTLED", ...}}` + 429 | Stage 12 |

## 5. Production Settings (`config/settings/prod.py`)

| Setting | Value |
|---|---|
| `DEBUG` | `False` (hardcoded) |
| `SECRET_KEY` | Required env var (raises `KeyError` if missing) |
| `SECURE_HSTS_SECONDS` | 31536000 (1 year) |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True` |
| `SECURE_HSTS_PRELOAD` | `True` |
| `SECURE_SSL_REDIRECT` | `True` (configurable via env) |
| `SECURE_PROXY_SSL_HEADER` | `("HTTP_X_FORWARDED_PROTO", "https")` |
| `SESSION_COOKIE_SECURE` | `True` |
| `CSRF_COOKIE_SECURE` | `True` |
| `SECURE_CONTENT_TYPE_NOSNIFF` | `True` |
| `X_FRAME_OPTIONS` | `"DENY"` |

## 6. CORS

| Check | Status |
|---|---|
| No wildcard origins | ✅ |
| Origins configurable via env | ✅ |
| Default `http://localhost:5173` (dev only) | ✅ |
| `CORS_ALLOW_CREDENTIALS = True` | ✅ |

## 7. AI Client Data Sharing

**What is sent to Anthropic:**
- Product title, description, brand, product_type (user-provided content)
- Product image URL (first image, if present)
- Candidate category IDs, names, full paths, keyword scores (internal taxonomy data)

**What is NOT sent:**
- `DJANGO_SECRET_KEY`, `ANTHROPIC_API_KEY`, DB credentials
- User PII or Shopify API tokens
- Internal system infrastructure details

**Notes:**
- Candidate category IDs are Django PKs (internal); acceptable since taxonomy
  is not considered sensitive data.
- AI calls use TLS (HTTPS) via the Anthropic SDK.
- `send_default_pii=False` set in Sentry config.

## 8. Dependency Vulnerabilities

`pip-audit` (August 2026): Django 5.1.15 has 6 known CVEs.
**Remediation:** Upgrade to Django ≥5.2.16 (major version bump, requires
separate planning).

## 9. Security Tests

| Test | File |
|---|---|
| Upload MIME-type rejection | `products/tests/test_security.py` |
| Unauthenticated import rejected (401) | `products/tests/test_import.py` |
| Throttle 429 returned when rate exceeded | `products/tests/test_security.py` |
| Upload extension whitelist enforced | `products/tests/test_import.py` |
| Review endpoints reject unauth (403) | `classification/tests/test_review_api.py` |
