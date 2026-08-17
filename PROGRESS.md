# Stage 14: DONE

Security audit and remediation pass.

## Changes

### Upload hardening (`products/services/import_service.py`)
- Added MIME-type secondary validation for `.csv` and `.xlsx` uploads
- Added `_sanitize_filename()` to strip path traversal and dangerous chars before DB storage
- Wrapped `_read_xlsx()` in try/except to catch `BadZipFile` (fake xlsx uploads)

### Endpoint permissions (`products/views.py`, `classification/views.py`)
- Changed `ProductImportCreateView` and `ProductImportDetailView` from `AllowAny` → `IsAuthenticated`
- Added `LoginThrottle` (10/min anon) to `LoginView`
- Added `ReviewWriteThrottle` (30/min user) to `ReviewApproveView` and `ReviewCorrectView`

### Global throttling (`config/settings/base.py`)
- Added `DEFAULT_THROTTLE_CLASSES`: `AnonRateThrottle` (60/min), `UserRateThrottle` (120/min)
- Global throttle exceptions already handled by custom exception handler (returns 429 + `THROTTLED` code)

### Production hardening (`config/settings/prod.py`)
- `SECURE_HSTS_SECONDS` = 31536000 (1 year), with subdomains + preload
- `SECURE_SSL_REDIRECT` = True (configurable via env)
- `SECURE_PROXY_SSL_HEADER` = `("HTTP_X_FORWARDED_PROTO", "https")`
- `SESSION_COOKIE_SECURE` = True, `CSRF_COOKIE_SECURE` = True
- `SECURE_CONTENT_TYPE_NOSNIFF` = True, `X_FRAME_OPTIONS` = "DENY"

### Security tests (`products/tests/test_security.py`)
- `UploadMimeTypeTest`: CSV accepted, .txt rejected, fake xlsx rejected, exe-as-csv rejected
- `UnauthenticatedAccessTest`: all protected endpoints return 401/403, public endpoints accessible
- `ThrottleResponseTest`: throttle 429 returns correct `{"error": {"code": "THROTTLED"}}` envelope

### Documentation
- Created `docs/security.md` with full audit checklist, permission matrix, throttle rates,
  prod settings table, CORS config, AI data-sharing inventory, and dependency status

### Test fixes
- Updated `products/tests/test_import.py`: added user authentication to `ProductImportAPITest`
- Updated `classification/tests/test_tasks.py`: added `force_authenticate` to `ImportTriggerTest`
- Updated 401→403 assertions where DRF `SessionAuthentication` returns 403 (CSRF context)

## Files Created
- `products/tests/test_security.py`
- `docs/security.md`

## Files Modified
- `products/services/import_service.py` — MIME validation, filename sanitization, xlsx error handling
- `products/views.py` — `IsAuthenticated` on import endpoints
- `classification/views.py` — LoginThrottle, ReviewWriteThrottle
- `config/settings/base.py` — global throttle classes + rates
- `config/settings/prod.py` — full production security hardening
- `products/tests/test_import.py` — added user auth to API tests
- `classification/tests/test_tasks.py` — added force_authenticate to ImportTriggerTest

## Test Status
- 246 tests, 0 failures
- New tests added: 14 (10 auth, 3 upload MIME, 1 throttle)

---

# Stage 15: NEXT
