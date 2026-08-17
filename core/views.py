import logging

from django.db import connection
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def _check_database():
    """Return True if the DB is reachable."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        logger.exception("Health check: database unreachable")
        return False


def _check_redis():
    """Return True if Redis is reachable (best-effort)."""
    from django.conf import settings

    try:
        import redis

        url = getattr(settings, "CELERY_BROKER_URL", "")
        if not url:
            return True  # No Redis configured — skip check.
        client = redis.from_url(url, socket_timeout=2)
        client.ping()
        return True
    except Exception:
        logger.exception("Health check: redis unreachable")
        return False


class HealthCheckView(APIView):
    """GET /api/health/ — returns 200 if all services are up, 503 otherwise.

    The ``X-Health-Status`` header is always set for quick proxy-level
    inspection without parsing the body.
    """

    permission_classes = []

    def get(self, request):
        db_ok = _check_database()
        redis_ok = _check_redis()

        healthy = db_ok and redis_ok
        status_code = 200 if healthy else 503
        status_label = "healthy" if healthy else "degraded"

        body = {
            "status": status_label,
            "checks": {
                "database": "ok" if db_ok else "fail",
                "redis": "ok" if redis_ok else "fail",
            },
        }

        response = Response(body, status=status_code)
        response["X-Health-Status"] = status_label
        return response
