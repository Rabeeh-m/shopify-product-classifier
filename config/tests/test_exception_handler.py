from django.test import SimpleTestCase
from rest_framework import exceptions as drf_exc
from rest_framework.test import APIRequestFactory

from config.exception_handlers import custom_exception_handler

factory = APIRequestFactory()


def _call(exc, view=None):
    """Helper: invoke the custom exception handler and return the response."""
    context = {"view": view or "test"}
    return custom_exception_handler(exc, context)


class TestCustomExceptionHandler(SimpleTestCase):
    def test_not_authenticated(self):
        resp = _call(drf_exc.NotAuthenticated())
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.data["error"]["code"], "NOT_AUTHENTICATED")
        self.assertIn("authentication", resp.data["error"]["message"].lower())

    def test_permission_denied(self):
        resp = _call(drf_exc.PermissionDenied("Access denied"))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["error"]["code"], "PERMISSION_DENIED")

    def test_not_found(self):
        resp = _call(drf_exc.NotFound("Widget not found"))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["error"]["code"], "NOT_FOUND")

    def test_unhandled_exception_returns_500(self):
        resp = _call(RuntimeError("kaboom"))
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.data["error"]["code"], "INTERNAL_ERROR")

    def test_validation_error_wraps_detail(self):
        exc = drf_exc.ValidationError({"name": ["This field is required."]})
        resp = _call(exc)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "ERROR")
        self.assertIn("name", resp.data["error"]["message"])

    def test_method_not_allowed(self):
        resp = _call(drf_exc.MethodNotAllowed("DELETE"))
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.data["error"]["code"], "METHOD_NOT_ALLOWED")
