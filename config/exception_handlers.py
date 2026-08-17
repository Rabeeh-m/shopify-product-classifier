import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

# Map known exception classes to (error_code, HTTP status) pairs.
_EXCEPTION_MAP = {
    "AuthenticationFailed": ("AUTH_FAILED", 401),
    "NotAuthenticated": ("NOT_AUTHENTICATED", 401),
    "PermissionDenied": ("PERMISSION_DENIED", 403),
    "NotFound": ("NOT_FOUND", 404),
    "MethodNotAllowed": ("METHOD_NOT_ALLOWED", 405),
    "Throttled": ("THROTTLED", 429),
}


def custom_exception_handler(exc, context):
    """DRF exception handler that wraps all errors in a consistent envelope.

    Successful responses are left untouched.  Any exception handled here
    produces::

        {
            "error": {
                "code": "<UPPER_SNAKE_CODE>",
                "message": "<human-readable message>"
            }
        }

    Unhandled exceptions (500s) are logged but still return the DRF
    default "detail" body so the client gets *some* response.
    """
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception — will become a 500.
        logger.exception(
            "Unhandled exception in %s: %s",
            context.get("view", "unknown"),
            exc,
        )
        return Response(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred.",
                }
            },
            status=500,
        )

    exc_class_name = type(exc).__name__
    code, _ = _EXCEPTION_MAP.get(exc_class_name, ("ERROR", response.status_code))

    # Normalise DRF's detail field into a consistent string.
    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
    elif isinstance(detail, list):
        message = "; ".join(str(d) for d in detail)
    else:
        message = str(detail)

    # Log client errors at warning, server errors at error.
    if response.status_code >= 500:
        logger.error("Server error [%s]: %s", code, message)
    elif response.status_code >= 400:
        logger.warning("Client error [%s]: %s", code, message)

    response.data = {"error": {"code": code, "message": message}}
    return response
