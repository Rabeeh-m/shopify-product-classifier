import types
from unittest.mock import MagicMock, patch

import anthropic
from django.test import TestCase

from classification.exceptions import AIClientError, AITimeoutError
from classification.services.ai_client import call_ai


def _make_api_status_error(status_code, message="error"):
    resp = MagicMock()
    resp.headers = {"request-id": "test-id"}
    resp.status_code = status_code
    return anthropic.APIStatusError(message=message, response=resp, body=None)


class AIClientMissingKeyTest(TestCase):
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False)
    def test_missing_api_key_raises(self):
        with self.assertRaises(AIClientError) as ctx:
            call_ai("test prompt")
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))


class AIClientSuccessTest(TestCase):
    @patch("classification.services.ai_client._get_anthropic_client")
    def test_success_returns_text(self, mock_get_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"category_id": 1}')]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = call_ai("test prompt")
        self.assertEqual(result, '{"category_id": 1}')
        mock_client.messages.create.assert_called_once()

    @patch("classification.services.ai_client._get_anthropic_client")
    def test_model_override(self, mock_get_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ok")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        call_ai("prompt", model="custom-model")
        call_args = mock_client.messages.create.call_args
        self.assertEqual(call_args.kwargs["model"], "custom-model")


class AIClientRetryTest(TestCase):
    @patch("classification.services.ai_client._get_anthropic_client")
    def test_timeout_retries_and_raises(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APITimeoutError(
            request=types.SimpleNamespace()
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AITimeoutError):
            call_ai("test prompt")
        self.assertEqual(mock_client.messages.create.call_count, 3)

    @patch("classification.services.ai_client._get_anthropic_client")
    def test_500_retries_and_raises(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _make_api_status_error(
            500, "Internal error"
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        self.assertEqual(mock_client.messages.create.call_count, 3)

    @patch("classification.services.ai_client._get_anthropic_client")
    def test_429_retries_and_raises(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _make_api_status_error(
            429, "Rate limited"
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        self.assertEqual(mock_client.messages.create.call_count, 3)

    @patch("classification.services.ai_client._get_anthropic_client")
    def test_400_raises_immediately(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _make_api_status_error(
            400, "Bad request"
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError) as ctx:
            call_ai("test prompt")
        self.assertIn("400", str(ctx.exception))
        mock_client.messages.create.assert_called_once()

    @patch("classification.services.ai_client._get_anthropic_client")
    def test_generic_api_error_retries(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="Connection error",
            request=types.SimpleNamespace(),
            body=None,
        )
        mock_get_client.return_value = mock_client

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        self.assertEqual(mock_client.messages.create.call_count, 3)
