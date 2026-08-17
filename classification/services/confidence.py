"""
Confidence scoring — adjusts the AI's self-reported confidence based on
how complete the product data was.  This is a pure function: it takes
plain data in and returns a float.  No database access.

Rules (evaluated in order; most severe applicable result wins):
  1. Title only (no description, no image) → cap at 50.
  2. No description (but image present) → cap at 65.
  3. No valid image (but description present) → 5-point penalty, floor 30.
  4. All data present → AI confidence passes through unchanged.

Rules are mutually exclusive — only the first applicable rule determines
the result.  This prevents penalties from stacking unfairly.
"""

import logging

logger = logging.getLogger(__name__)

_TITLE_ONLY_CAP = 50
_NO_DESCRIPTION_CAP = 65
_NO_IMAGE_PENALTY = 5
_NO_IMAGE_FLOOR = 30


def _has_description(product):
    """Return True if the product has a non-blank description."""
    return bool((product.description or "").strip())


def _has_image(product):
    """Return True if at least one valid image URL exists."""
    if not hasattr(product, "images"):
        return False
    first_img = product.images.first()
    return first_img is not None and bool((first_img.url or "").strip())


def calculate_confidence(product, ai_response):
    """Adjust the AI's self-reported confidence for data completeness.

    Args:
        product: A Product instance (must have title, description, and
            an optional images reverse relation).
        ai_response: The parsed dict returned by classifier.py
            (contains 'confidence' key).

    Returns:
        A float between 0.0 and 100.0 representing the adjusted
        confidence score.
    """
    ai_confidence = ai_response["confidence"]
    title = (product.title or "").strip()
    has_desc = _has_description(product)
    has_img = _has_image(product)

    adjusted = float(ai_confidence)

    if not has_desc and not has_img:
        # Rule 1: title only — nothing else useful
        adjusted = min(adjusted, _TITLE_ONLY_CAP)
        logger.debug(
            "Title-only cap (%s): %.1f → %.1f",
            title,
            ai_confidence,
            adjusted,
        )
    elif not has_desc:
        # Rule 2: no description, but image present
        adjusted = min(adjusted, _NO_DESCRIPTION_CAP)
        logger.debug(
            "No-description cap (%s): %.1f → %.1f",
            title,
            ai_confidence,
            adjusted,
        )
    elif not has_img:
        # Rule 3: no image, but description present — minor penalty
        before = adjusted
        adjusted = max(adjusted - _NO_IMAGE_PENALTY, _NO_IMAGE_FLOOR)
        if adjusted < before:
            logger.debug(
                "No-image penalty (%s): %.1f → %.1f",
                title,
                before,
                adjusted,
            )

    adjusted = max(0.0, min(100.0, adjusted))

    logger.debug(
        "Confidence adjustment for '%s': %.1f → %.1f",
        title,
        ai_confidence,
        adjusted,
    )
    return adjusted
