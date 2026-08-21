import json
import os
import types
from unittest.mock import patch

from django.test import TestCase, override_settings

from classification.exceptions import (
    AIClientError,
    AITimeoutError,
    ClassificationParseError,
)
from classification.services.classifier import (
    _build_prompt,
    _parse_and_validate,
    classify_product,
)

# Use a non-existent key for tests — we never hit the real API.
_FAKE_CANDIDATES = [
    types.SimpleNamespace(
        category=types.SimpleNamespace(
            id=10, name="Sofas", full_path="Furniture > Sofas"
        ),
        score=6.5,
    ),
    types.SimpleNamespace(
        category=types.SimpleNamespace(
            id=20, name="Chairs", full_path="Furniture > Chairs"
        ),
        score=3.0,
    ),
    types.SimpleNamespace(
        category=types.SimpleNamespace(
            id=30, name="Tables", full_path="Furniture > Tables"
        ),
        score=1.5,
    ),
]

_FAKE_PRODUCT = types.SimpleNamespace(
    title="Leather Sofa",
    description="A comfortable brown leather sofa",
    brand="Acme",
    product_type="Furniture",
    images=types.SimpleNamespace(
        first=lambda: types.SimpleNamespace(url="https://example.com/sofa.jpg")
    ),
)


def _good_response():
    return json.dumps(
        {
            "chosen_category_id": 10,
            "alternatives": [
                {"category_id": 20, "confidence": 25.0},
                {"category_id": 30, "confidence": 10.0},
            ],
            "attributes": [
                {"name": "Color", "value": "Brown"},
                {"name": "Material", "value": "Leather"},
            ],
            "confidence": 82.5,
            "reasoning": (
                "Product is explicitly a leather sofa, matching " "the Sofas category."
            ),
        }
    )


def _make_api_status_error(status_code, message="error"):
    """Create a genai APIError with the given HTTP status code."""

    from google.genai import errors as genai_errors

    err_cls = (
        genai_errors.ServerError if status_code >= 500 else genai_errors.ClientError
    )
    return err_cls(
        status_code,
        {"message": message, "error": {"code": status_code, "message": message}},
    )


class BuildPromptTest(TestCase):
    def test_prompt_contains_product_fields(self):
        prompt = _build_prompt(_FAKE_PRODUCT, _FAKE_CANDIDATES)
        self.assertIn("Leather Sofa", prompt)
        self.assertIn("comfortable brown leather sofa", prompt)
        self.assertIn("Acme", prompt)
        self.assertIn("Furniture", prompt)

    def test_prompt_contains_candidate_ids(self):
        prompt = _build_prompt(_FAKE_PRODUCT, _FAKE_CANDIDATES)
        self.assertIn("id: 10", prompt)
        self.assertIn("id: 20", prompt)
        self.assertIn("id: 30", prompt)

    def test_prompt_contains_candidate_names(self):
        prompt = _build_prompt(_FAKE_PRODUCT, _FAKE_CANDIDATES)
        self.assertIn("Sofas", prompt)
        self.assertIn("Chairs", prompt)
        self.assertIn("Tables", prompt)

    def test_prompt_contains_image_url(self):
        prompt = _build_prompt(_FAKE_PRODUCT, _FAKE_CANDIDATES)
        self.assertIn("https://example.com/sofa.jpg", prompt)

    def test_prompt_handles_no_image(self):
        product = types.SimpleNamespace(
            title="Test",
            description="",
            brand="",
            product_type="",
            images=types.SimpleNamespace(first=lambda: None),
        )
        prompt = _build_prompt(product, _FAKE_CANDIDATES)
        self.assertNotIn("image URL", prompt)

    def test_prompt_handles_minimal_product(self):
        product = types.SimpleNamespace(
            title="Widget",
            description="",
            brand="",
            product_type="",
            images=types.SimpleNamespace(first=lambda: None),
        )
        prompt = _build_prompt(product, _FAKE_CANDIDATES)
        self.assertIn("Widget", prompt)
        self.assertIn("(none)", prompt)


class ParseAndValidateTest(TestCase):
    def test_valid_response(self):
        result = _parse_and_validate(_good_response(), {10, 20, 30})
        self.assertEqual(result["chosen_category_id"], 10)
        self.assertEqual(result["confidence"], 82.5)
        self.assertEqual(len(result["alternatives"]), 2)
        self.assertEqual(len(result["attributes"]), 2)
        self.assertIn("leather sofa", result["reasoning"].lower())

    def test_invalid_json_raises(self):
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate("not json at all {{{", {10, 20})
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_non_object_json_raises(self):
        with self.assertRaises(ClassificationParseError):
            _parse_and_validate('["not", "an", "object"]', {10, 20})

    def test_missing_chosen_category_id_raises(self):
        resp = json.dumps({"confidence": 80, "reasoning": "test"})
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate(resp, {10, 20})
        self.assertIn("chosen_category_id", str(ctx.exception))

    def test_chosen_id_not_in_candidates_raises(self):
        resp = json.dumps(
            {
                "chosen_category_id": 999,
                "confidence": 80,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate(resp, {10, 20, 30})
        self.assertIn("999", str(ctx.exception))
        self.assertIn("not in the candidate list", str(ctx.exception))

    def test_missing_confidence_raises(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError):
            _parse_and_validate(resp, {10})

    def test_confidence_out_of_range_raises(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "confidence": 150,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate(resp, {10})
        self.assertIn("out of range", str(ctx.exception))

    def test_negative_confidence_raises(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "confidence": -5,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError):
            _parse_and_validate(resp, {10})

    def test_alternatives_must_be_list(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "confidence": 80,
                "alternatives": "not a list",
                "attributes": [],
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError):
            _parse_and_validate(resp, {10})

    def test_attributes_must_be_list(self):
        resp = json.dumps(
            {
                "chosen_category_id": 10,
                "confidence": 80,
                "alternatives": [],
                "attributes": "not a list",
                "reasoning": "test",
            }
        )
        with self.assertRaises(ClassificationParseError):
            _parse_and_validate(resp, {10})

    def test_raw_response_preserved_on_error(self):
        raw = "garbage output"
        with self.assertRaises(ClassificationParseError) as ctx:
            _parse_and_validate(raw, {10})
        self.assertEqual(ctx.exception.raw_response, raw)


class ClassifyProductTest(TestCase):
    @patch("classification.services.classifier.call_ai")
    def test_successful_classification(self, mock_call_ai):
        mock_call_ai.return_value = _good_response()
        result = classify_product(_FAKE_PRODUCT, _FAKE_CANDIDATES)
        self.assertEqual(result["chosen_category_id"], 10)
        self.assertEqual(result["confidence"], 82.5)
        mock_call_ai.assert_called_once()

    @patch("classification.services.classifier.call_ai")
    def test_no_candidates_raises(self, mock_call_ai):
        with self.assertRaises(ClassificationParseError) as ctx:
            classify_product(_FAKE_PRODUCT, [])
        self.assertIn("No candidates", str(ctx.exception))
        mock_call_ai.assert_not_called()

    @patch("classification.services.classifier.call_ai")
    def test_ai_returns_invalid_json(self, mock_call_ai):
        mock_call_ai.return_value = "this is not json"
        with self.assertRaises(ClassificationParseError):
            classify_product(_FAKE_PRODUCT, _FAKE_CANDIDATES)

    @patch("classification.services.classifier.call_ai")
    def test_ai_chooses_invalid_category(self, mock_call_ai):
        resp = json.dumps(
            {
                "chosen_category_id": 999,
                "confidence": 80,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        mock_call_ai.return_value = resp
        with self.assertRaises(ClassificationParseError):
            classify_product(_FAKE_PRODUCT, _FAKE_CANDIDATES)

    @patch("classification.services.classifier.call_ai")
    def test_api_error_propagates(self, mock_call_ai):
        mock_call_ai.side_effect = AIClientError("API down")
        with self.assertRaises(AIClientError):
            classify_product(_FAKE_PRODUCT, _FAKE_CANDIDATES)

    @patch("classification.services.classifier.call_ai")
    def test_timeout_propagates(self, mock_call_ai):
        mock_call_ai.side_effect = AITimeoutError("timed out")
        with self.assertRaises(AITimeoutError):
            classify_product(_FAKE_PRODUCT, _FAKE_CANDIDATES)

    @patch("classification.services.classifier.call_ai")
    def test_alternatives_and_attributes_parsed(self, mock_call_ai):
        mock_call_ai.return_value = _good_response()
        result = classify_product(_FAKE_PRODUCT, _FAKE_CANDIDATES)
        self.assertEqual(result["alternatives"][0]["category_id"], 20)
        self.assertEqual(result["attributes"][0]["name"], "Color")
        self.assertEqual(result["attributes"][0]["value"], "Brown")


class RetryLogicTest(TestCase):
    @patch("classification.services.classifier.call_ai")
    def test_timeout_retries_then_raises(self, mock_call_ai):
        mock_call_ai.side_effect = AITimeoutError("connection timed out")
        with self.assertRaises(AITimeoutError):
            classify_product(_FAKE_PRODUCT, _FAKE_CANDIDATES)
        # call_ai wraps the retry logic internally
        self.assertEqual(mock_call_ai.call_count, 1)

    @override_settings(AI_RATE_LIMIT_RPM=0)
    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_client_timeout_retries(self, mock_get_client, mock_sleep):
        import httpx

        mock_client = mock_get_client.return_value
        mock_client.models.generate_content.side_effect = httpx.ReadTimeout(
            "timed out"
        )
        from classification.services.ai_client import call_ai

        with self.assertRaises(AITimeoutError):
            call_ai("test prompt")
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @override_settings(AI_RATE_LIMIT_RPM=0)
    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_server_error_retries(self, mock_get_client, mock_sleep):
        mock_client = mock_get_client.return_value
        mock_client.models.generate_content.side_effect = _make_api_status_error(
            500, "Internal error"
        )
        from classification.services.ai_client import call_ai

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @override_settings(AI_RATE_LIMIT_RPM=0)
    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_rate_limit_retries(self, mock_get_client, mock_sleep):
        mock_client = mock_get_client.return_value
        mock_client.models.generate_content.side_effect = _make_api_status_error(
            429, "Rate limited"
        )
        from classification.services.ai_client import call_ai

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @override_settings(AI_RATE_LIMIT_RPM=0)
    @patch("classification.services.ai_client.time.sleep")
    @patch("classification.services.ai_client._get_gemini_client")
    def test_client_error_no_retry(self, mock_get_client, mock_sleep):
        mock_client = mock_get_client.return_value
        mock_client.models.generate_content.side_effect = _make_api_status_error(
            400, "Bad request"
        )
        from classification.services.ai_client import call_ai

        with self.assertRaises(AIClientError):
            call_ai("test prompt")
        # 4xx (non-429) should NOT retry
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

    @patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False)
    def test_missing_api_key_fails_fast(self):
        from classification.services.ai_client import call_ai

        with self.assertRaises(AIClientError) as ctx:
            call_ai("test prompt")
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))
