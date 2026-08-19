# Deployment Guide

> Cross-references: [README.md](../README.md) | [Architecture](architecture.md) | [Security](security.md) | [Runbook](runbook.md)

## Overview

The production deployment uses Docker Compose with six services:

| Service | Image | Purpose |
|---------|-------|---------|
| `web` | Backend Dockerfile | Django + gunicorn (WSGI server) |
| `worker` | Backend Dockerfile | Celery worker for classification |
| `beat` | Backend Dockerfile | Celery beat scheduler (stuck-product recovery) |
| `db` | `mariadb:10.11` | MariaDB database |
| `redis` | `redis:7-alpine` | Celery broker + Django cache |
| `frontend` | Frontend Dockerfile | nginx serving the React/Vite build |

## Prerequisites

- Docker Engine 24+ and Docker Compose v2+
- A server with at least 2 GB RAM (the classification worker is the memory bottleneck)
- An Anthropic API key
- A domain name with TLS termination (nginx/Cloudflare/etc.) — the stack exposes HTTP internally; TLS is handled by your reverse proxy

## Environment Variables

Create a `.env` file in the project root. Every variable below is required for production unless marked optional.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | **Yes** | — | Django secret key (generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`) |
| `DJANGO_ENV` | **Yes** | `prod` | Must be `prod` for production settings |
| `ALLOWED_HOSTS` | **Yes** | — | Comma-separated hostnames (e.g. `example.com,www.example.com`) |
| `ANTHROPIC_API_KEY` | **Yes** | — | Anthropic API key for LLM classification |
| `DB_NAME` | **Yes** | `shopify_product_classifier` | MariaDB database name |
| `DB_USER` | **Yes** | `root` | MariaDB user |
| `DB_PASSWORD` | **Yes** | — | MariaDB password |
| `DB_HOST` | **Yes** | `db` | MariaDB host (use `db` for Docker Compose) |
| `DB_PORT` | No | `3306` | MariaDB port |
| `CELERY_BROKER_URL` | **Yes** | `redis://redis:6379/0` | Redis URL for Celery broker |
| `CELERY_RESULT_BACKEND` | No | `django-db` | Celery result storage |
| `REDIS_URL` | **Yes** | `redis://redis:6379/1` | Redis URL for Django cache |
| `CORS_ALLOWED_ORIGINS` | **Yes** | — | Comma-separated frontend origins (e.g. `https://example.com`) |
| `MAX_UPLOAD_SIZE_MB` | No | `10` | Maximum upload file size |
| `AI_MODEL_NAME` | No | `claude-sonnet-4-20250514` | Anthropic model |
| `AI_REQUEST_TIMEOUT` | No | `30` | LLM request timeout (seconds) |
| `CLASSIFICATION_CANDIDATE_LIMIT` | No | `15` | Max candidate categories for LLM |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | No | `70` | Confidence threshold for auto-approve vs review |
| `CLASSIFICATION_MAX_RETRIES` | No | `3` | Per-product retry limit |
| `CLASSIFICATION_CONCURRENCY_LIMIT` | No | `5` | Thread pool workers per batch |
| `TAXONOMY_CACHE_TTL` | No | `3600` | Taxonomy cache TTL (seconds) |
| `GUNICORN_WORKERS` | No | `4` | Gunicorn worker count |
| `GUNICORN_TIMEOUT` | No | `120` | Gunicorn request timeout (seconds) |
| `GUNICORN_BIND` | No | `0.0.0.0:8000` | Gunicorn bind address |
| `SENTRY_DSN` | No | — | Sentry DSN for error tracking |
| `SECURE_HSTS_SECONDS` | No | `31536000` | HSTS header max-age |
| `SECURE_SSL_REDIRECT` | No | `True` | Redirect HTTP to HTTPS |

See [`.env.example`](../.env.example) for a template.

## Deploy Procedure

### 1. Clone and configure

```bash
git clone <repo-url> && cd shopify-product-classifier
cp .env.example .env
# Edit .env with production values (see table above)
```

### 2. Build and start the stack

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

The `web` container automatically runs migrations on first start (via `RUN_MIGRATIONS=true` set in the compose file) and collects static files.

### 3. Load taxonomy data

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py load_taxonomy --source taxonomy/fixtures/sample_taxonomy.json
```

### 4. Create a superuser

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

### 5. Verify the deployment

```bash
# Health check
curl http://localhost/api/health/

# Should return:
# {"status": "healthy", "checks": {"database": "ok", "redis": "ok"}}
```

### 6. Set up TLS

Place a TLS-terminating reverse proxy (nginx, Cloudflare, AWS ALB, etc.) in front of the `frontend` container on port 80. The application sets `SECURE_PROXY_SSL_HEADER` so Django trusts `X-Forwarded-Proto: https` from the proxy.

## Updating

```bash
git pull
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d --remove-orphans
```

Migrations run automatically on container start. The `worker` and `beat` containers restart with the new code.

## Rollback

If a deploy goes wrong:

```bash
# 1. Check out the previous release
git checkout <previous-commit-hash>

# 2. Rebuild and restart
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# 3. If migrations need to be reversed, run:
docker compose -f docker-compose.prod.yml exec web python manage.py migrate <app_name> <previous_migration_name>
```

Database migrations are the primary risk during rollback. If the new release added migrations that the rollback removes, you'll need to manually reverse them. Keep migrations simple and backward-compatible to minimize rollback risk.

## Concurrent Migration Safety

The entrypoint script uses `flock` to prevent multiple containers from running migrations simultaneously. However, the recommended approach is:

1. **Run migrations as a one-off step** (not in every container startup):
   ```bash
   docker compose -f docker-compose.prod.yml run --rm web python manage.py migrate
   ```
2. **Start containers without migration** by removing `RUN_MIGRATIONS=true` from the compose file (or setting it to `false`).

This avoids any race condition and gives you explicit control over when schema changes apply.

## Volumes and File Storage

| Data | Location | Strategy |
|------|----------|----------|
| MariaDB data | `mariadb_data` Docker volume | Persistent, managed by Docker |
| Media uploads | `/app/media` (container) | Bind-mount a host directory or shared volume for multi-replica setups |
| Static files | `/app/staticfiles` (baked into image) | Collected at build time |

For multi-replica or cloud deployments, replace the on-disk `MEDIA_ROOT` with an object storage backend (e.g. S3 via `django-storages`). The current setup uses local disk, suitable for single-server deployments.

## Troubleshooting

### Container won't start — "DJANGO_SECRET_KEY not set"

Add `DJANGO_SECRET_KEY` to your `.env` file. The production settings require it (no fallback).

### "Access denied for user" on MariaDB

Ensure `DB_PASSWORD` in `.env` matches the `MYSQL_ROOT_PASSWORD` set in docker-compose. If you changed the password after first start, the existing MariaDB volume has the old password — either reset the volume (`docker volume rm`) or update the password in MariaDB directly.

### Health check returns 503

Check individual service health:
```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs web
docker compose -f docker-compose.prod.yml logs redis
```

### Worker not processing classification tasks

Ensure the worker container is running and connected to Redis:
```bash
docker compose -f docker-compose.prod.yml logs worker
```

Common causes: wrong `CELERY_BROKER_URL`, Redis not reachable, or no pending products.

### Media files not persisting across restarts

Add a volume mount for media in docker-compose.prod.yml:
```yaml
web:
  volumes:
    - media_data:/app/media
# ...
volumes:
  media_data:
```
