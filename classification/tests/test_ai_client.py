import threading
import time
from unittest.mock import MagicMock, patch

import httpx
from django.test import TestCase, override_settings
from google.genai import errors as genai_errors

from classification.exceptions import AIClientError, AITimeoutError
from classification.services.ai_client import (
    _compute_backoff,
    _extract_retry_delay,
    _get_rate_limiter,
    _RateLimiter,
    call_ai,
)


def _make_api_status_error(status_code, message="error"):
    err_cls = (
        genai_errors.ServerError if status_code >= 500 else genai_errors.ClientError
    )
    return err_cls(
        status_code,
        {"message": message, "error": {"code": status_code, "message": message}},
    )


@override_settings(AI_RATE_LIMIT_RPM=0)
class AIClientMissingKeyTest(TestCase):
    @patch.dict("os.environ", {"GEMINI_API_KEY": ""}, clear=False)
    def test_missing_api_key_raises(self):
        with self.assertRaises(AIClientError) as ctx:
            call_ai("test prompt")
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))


@override_settings(AI_RATE_LIMIT_RPM=0)
class AIClientSuccessTest(TestCase):
    @patch("classification.services.ai_client._get_gemini_client")
    def test_success_returns_text(self, mock_get_client):
        mock_response = MagicMock()
        mock_response.text = '{"category_id": 1}'
        mock_response.usage_metadata.prompt_token_count = 100
        mock_response.usage_metadata.candidates_token_count = 50
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = call_ai("test prompt")
        self.assertEqual(result, '{"category_id": 1}')
        mock_client.models.generate_content.assert_called_once()

    @patch("classification.services.ai_client._get_gemini_client")
    def test_model_override(self, mock_get_client):
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        call_ai("prompt", model="custom-model")
        call_args = mock_client.models.generate_content.call_args
        self.assertEqual(call_args.kwargs["model"], "custom-model")


@override_settings(AI_RATE_LIMIT_RPM=0)
class AIClientRetryTest(TestCase):
    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_timeout_retries_and_raises(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = httpx.ReadTimeout(
            "timed out"
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AITimeoutError):
            call_ai("test prompt")
        self.assertEqual(mock_client.models.generate_content.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_500_retries_and_raises(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _make_api_status_error(
            500, "Internal error"
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_429_retries_and_raises(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _make_api_status_error(
            429, "Rate limited"
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_429_honors_server_retry_delay(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _make_api_status_error(
            429,
            "Quota exceeded ... Please retry in 48.113410",
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError):
            call_ai("test prompt")

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(delays), 2)
        for delay in delays:
            self.assertGreaterEqual(delay, 48.0)
            self.assertLessEqual(delay, 120.0)

    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_400_raises_immediately(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _make_api_status_error(
            400, "Bad request"
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError) as ctx:
            call_ai("test prompt")
        self.assertIn("400", str(ctx.exception))
        mock_client.models.generate_content.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_generic_api_error_retries(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = genai_errors.APIError(
            500,
            {"message": "Connection error", "error": {"code": 500}},
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_success_on_second_attempt(self, mock_get_client, mock_sleep):
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            _make_api_status_error(429, "Please retry in 1.5"),
            mock_response,
        ]
        mock_get_client.return_value = mock_client

        result = call_ai("test prompt")
        self.assertEqual(result, "ok")
        self.assertEqual(mock_client.models.generate_content.call_count, 2)


class BackoffHelpersTest(TestCase):
    def test_extract_retry_delay_from_message(self):
        exc = _make_api_status_error(
            429, "Quota exceeded... Please retry in 48.113410"
        )
        self.assertAlmostEqual(_extract_retry_delay(exc), 48.113410)

    def test_extract_retry_delay_absent(self):
        exc = _make_api_status_error(500, "Internal error")
        self.assertIsNone(_extract_retry_delay(exc))

    def test_compute_backoff_grows_exponentially(self):
        d1 = _compute_backoff(1, 2.0)
        d2 = _compute_backoff(2, 2.0)
        d3 = _compute_backoff(3, 2.0)
        self.assertLessEqual(d1, 2.5)
        self.assertGreaterEqual(d2, 4.0)
        self.assertLessEqual(d2, 5.0)
        self.assertGreaterEqual(d3, 8.0)
        self.assertLessEqual(d3, 10.0)

    def test_compute_backoff_respects_server_hint(self):
        delay = _compute_backoff(1, 2.0, server_delay=45.0)
        self.assertGreaterEqual(delay, 45.0)

    def test_compute_backoff_caps_server_hint(self):
        delay = _compute_backoff(1, 2.0, server_delay=9999.0)
        self.assertLessEqual(delay, 120.0)


class RateLimiterTest(TestCase):
    @override_settings(AI_RATE_LIMIT_RPM=0)
    def test_disabled_when_rpm_zero(self):
        self.assertIsNone(_get_rate_limiter())

    @override_settings(AI_RATE_LIMIT_RPM=15)
    def test_enabled_and_shared_per_rpm(self):
        limiter = _get_rate_limiter()
        self.assertIsNotNone(limiter)
        self.assertIs(limiter, _get_rate_limiter())

    @override_settings(AI_RATE_LIMIT_RPM=0)
    def test_acquire_allows_burst_up_to_limit(self):
        limiter = _RateLimiter(3)
        start = time.monotonic()
        for _ in range(3):
            limiter.acquire()
        self.assertLess(time.monotonic() - start, 1.0)

    @override_settings(AI_RATE_LIMIT_RPM=0)
    def test_acquire_blocks_beyond_limit(self):
        limiter = _RateLimiter(2)
        limiter.acquire()
        limiter.acquire()

        sleeper = MagicMock()
        with patch(
            "classification.services.ai_client.time.sleep", side_effect=sleeper
        ) as mock_sleep:
            # Simulate window expiry after first wait so acquire() returns.
            def _expire_window(_seconds):
                limiter._timestamps.clear()

            mock_sleep.side_effect = _expire_window
            limiter.acquire()
            mock_sleep.assert_called()

    @override_settings(AI_RATE_LIMIT_RPM=0)
    def test_concurrent_threads_respect_limit(self):
        rpm = 5
        limiter = _RateLimiter(rpm)
        allowed = []
        lock = threading.Lock()

        def worker():
            limiter.acquire()
            with lock:
                allowed.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(rpm)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(allowed), rpm)
