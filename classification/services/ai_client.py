import logging
import os

import anthropic

from classification.exceptions import AIClientError, AITimeoutError

logger = logging.getLogger(__name__)

# Future option: OpenAI client could be added here with the same interface.
# The function signatures below are provider-agnostic; only _call_anthropic
# needs swapping or wrapping.


def _get_anthropic_client():
    """Lazily instantiate and return an Anthropic client.

    Raises AIClientError immediately if the API key is missing, so callers
    fail fast rather than hitting a cryptic error mid-request.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise AIClientError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Add it to your .env file or export it in your shell."
        )
    return anthropic.Anthropic(api_key=api_key)


def call_ai(prompt, *, model=None, max_tokens=1024, timeout=30):
    """Send a prompt to the AI model and return the raw text response.

    Args:
        prompt: The full user prompt string.
        model: Model name override. Defaults to settings.AI_MODEL_NAME.
        max_tokens: Max tokens in the response.
        timeout: Request timeout in seconds.

    Returns:
        The model's response as a string.

    Raises:
        AIClientError on API errors (after retries are exhausted).
        AITimeoutError on explicit timeout failures.
    """
    from django.conf import settings

    if model is None:
        model = getattr(settings, "AI_MODEL_NAME", "claude-sonnet-4-20250514")

    client = _get_anthropic_client()
    max_retries = 3
    last_exc = None

    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                timeout=timeout,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            logger.debug("AI response (attempt %d): %s", attempt, text)
            return text
        except anthropic.APITimeoutError as exc:
            last_exc = AITimeoutError(
                f"AI API timed out after {timeout}s (attempt {attempt}/"
                f"{max_retries}): {exc}"
            )
            logger.warning(
                "AI timeout on attempt %d/%d: %s",
                attempt,
                max_retries,
                exc,
            )
        except anthropic.APIStatusError as exc:
            status = exc.status_code
            if status >= 500 or status == 429:
                last_exc = AIClientError(
                    f"AI API error {status} (attempt {attempt}/"
                    f"{max_retries}): {exc}"
                )
                logger.warning(
                    "AI API error %d on attempt %d/%d: %s",
                    status,
                    attempt,
                    max_retries,
                    exc,
                )
            else:
                raise AIClientError(f"AI API error {status}: {exc}") from exc
        except anthropic.APIError as exc:
            last_exc = AIClientError(
                f"AI API error (attempt {attempt}/{max_retries}): {exc}"
            )
            logger.warning(
                "AI API error on attempt %d/%d: %s",
                attempt,
                max_retries,
                exc,
            )

    raise last_exc
