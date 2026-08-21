import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

_EXCEPTION_MAP = {
    "AuthenticationFailed": ("AUTH_FAILED", 401),
    "NotAuthenticated": ("NOT_AUTHENTICATED", 401),
    "PermissionDenied": ("PERMISSION_DENIED", 403),
    "NotFound": ("NOT_FOUND", 404),
    "MethodNotAllowed": ("METHOD_NOT_ALLOWED", 405),
}


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
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

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
    elif isinstance(detail, list):
        message = "; ".join(str(d) for d in detail)
    else:
        message = str(detail)

    if response.status_code >= 500:
        logger.error("Server error [%s]: %s", code, message)
    elif response.status_code >= 400:
        logger.warning("Client error [%s]: %s", code, message)

    response.data = {"error": {"code": code, "message": message}}
    return response
