import logging
import os
import random
import re
import threading
import time
from collections import deque

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from classification.exceptions import AIClientError, AITimeoutError

logger = logging.getLogger(__name__)

# Matches hints like "Please retry in 48.113410" embedded in API error
# messages (Gemini includes these on 429 RESOURCE_EXHAUSTED).
_RETRY_DELAY_RE = re.compile(
    r"retry in ([0-9]+(?:\.[0-9]+)?)(?:s| ?seconds?)?", re.IGNORECASE
)

# Upper bound for any single retry sleep, so a bogus server hint cannot
# stall a worker indefinitely.
_MAX_RETRY_DELAY_SECONDS = 120.0


class RateLimiter:
    """Thread-safe sliding-window rate limiter (requests per minute)."""

    def __init__(self, rpm):
        self.rpm = rpm
        self._lock = threading.Lock()
        self._timestamps = deque()

    def acquire(self):
        """Block until a request slot is available, then record it."""
        while True:
            with self._lock:
                now = time.monotonic()
                window_start = now - 60.0
                while self._timestamps and self._timestamps[0] <= window_start:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.rpm:
                    self._timestamps.append(now)
                    return
                wait = self._timestamps[0] + 60.0 - now
            time.sleep(max(wait, 0.05))


_limiter = None
_limiter_lock = threading.Lock()


def _get_rate_limiter():
    from django.conf import settings

    global _limiter
    rpm = int(getattr(settings, "AI_RATE_LIMIT_RPM", 0) or 0)
    if rpm <= 0:
        return None
    with _limiter_lock:
        if _limiter is None:
            _limiter = RateLimiter(rpm)
        return _limiter


def _extract_retry_delay(exc):
    """Pull the server-suggested retry delay (seconds) out of an error message."""
    match = _RETRY_DELAY_RE.search(str(exc))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _compute_backoff(attempt, base_delay, server_delay=None):
    """Exponential backoff with jitter, never shorter than the server hint."""
    delay = base_delay * (2 ** (attempt - 1))
    delay += random.uniform(0, delay * 0.25)
    if server_delay is not None:
        delay = max(delay, min(server_delay, _MAX_RETRY_DELAY_SECONDS))
    return min(delay, _MAX_RETRY_DELAY_SECONDS)


def _get_gemini_client(timeout=30):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise AIClientError(
            "GEMINI_API_KEY environment variable is not set. "
            "Add it to your .env file or export it in your shell."
        )
    return genai.Client(
        api_key=api_key,
        http_options=genai_types.HttpOptions(timeout=timeout * 1000),
    )


def call_ai(prompt, *, model=None, max_tokens=1024, timeout=30):
    """Send a prompt to the AI model and return the raw text response.

    Requests are paced through the shared rate limiter; transient failures
    retry with exponential backoff honoring any server-provided delay.
    """
    from django.conf import settings

    if model is None:
        model = getattr(settings, "AI_MODEL_NAME", "gemini-3.5-flash-lite")

    client = _get_gemini_client(timeout=timeout)
    limiter = _get_rate_limiter()
    max_retries = int(getattr(settings, "AI_RETRY_MAX_ATTEMPTS", 3))
    base_delay = float(getattr(settings, "AI_RETRY_BASE_DELAY", 2.0))
    last_exc = None

    for attempt in range(1, max_retries + 1):
        if limiter is not None:
            limiter.acquire()
        start = time.monotonic()
        server_delay = None
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                ),
            )
            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "ai_call model=%s attempt=%d latency_ms=%.0f",
                model,
                attempt,
                latency_ms,
            )
            return response.text
        except httpx.TimeoutException as exc:
            last_exc = AITimeoutError(
                f"AI API timed out after {timeout}s (attempt {attempt}/"
                f"{max_retries}): {exc}"
            )
            logger.warning("ai_timeout attempt=%d/%d: %s", attempt, max_retries, exc)
            server_delay = _extract_retry_delay(exc)
        except genai_errors.APIError as exc:
            status = exc.code
            if status >= 500 or status == 429:
                last_exc = AIClientError(
                    f"AI API error {status} (attempt {attempt}/"
                    f"{max_retries}): {exc}"
                )
                logger.warning(
                    "ai_error status=%d attempt=%d/%d: %s",
                    status,
                    attempt,
                    max_retries,
                    exc,
                )
            else:
                raise AIClientError(f"AI API error {status}: {exc}") from exc

            server_delay = _extract_retry_delay(exc)

        if attempt < max_retries:
            delay = _compute_backoff(attempt, base_delay, server_delay)
            logger.info("ai_retry_backoff attempt=%d sleeping %.1fs", attempt, delay)
            time.sleep(delay)

    raise last_exc
