import os

from config.settings.base import *  # noqa: F401, F403

DEBUG = False

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

# --- Security hardening ---

# HSTS: tell browsers to only use HTTPS for 1 year (include subdomains,
# allow preload list submission).  Set to 0 in dev/staging.
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Redirect all HTTP to HTTPS (disable behind a TLS-terminating proxy that
# already handles this by setting SECURE_PROXY_SSL_HEADER).
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True").lower() in (
    "true",
    "1",
    "yes",
)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Cookies
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Misc
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# --- Cache: Redis-backed ---

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/1")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# --- Static & media files ---

STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405

# Media files: stored on disk by default. For multi-replica or cloud
# deployments, override MEDIA_ROOT to point at a shared volume or
# object-storage mount (e.g. S3 via django-storages).
MEDIA_ROOT = BASE_DIR / "media"  # noqa: F405

# Gunicorn settings (configurable via env vars)
GUNICORN_WORKERS = int(os.environ.get("GUNICORN_WORKERS", "4"))
GUNICORN_TIMEOUT = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
GUNICORN_BIND = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
