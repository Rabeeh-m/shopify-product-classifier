import json
import logging

from classification.exceptions import ClassificationParseError
from classification.services.ai_client import call_ai

logger = logging.getLogger(__name__)

# Data-completeness adjustments to the AI's self-reported confidence:
#   title only → cap 50, no description → cap 65, no image → -5 (floor 30).
_TITLE_ONLY_CAP = 50.0
_NO_DESCRIPTION_CAP = 65.0
_NO_IMAGE_PENALTY = 5.0
_NO_IMAGE_FLOOR = 30.0


def _has_image(product):
    first_img = product.images.first() if hasattr(product, "images") else None
    return first_img is not None and bool((first_img.url or "").strip())


def adjust_confidence(product, confidence):
    """Penalize the AI's confidence when product data is incomplete."""
    has_desc = bool((product.description or "").strip())
    has_img = _has_image(product)

    if not has_desc and not has_img:
        return min(float(confidence), _TITLE_ONLY_CAP)
    if not has_desc:
        return min(float(confidence), _NO_DESCRIPTION_CAP)
    if not has_img:
        return max(float(confidence) - _NO_IMAGE_PENALTY, _NO_IMAGE_FLOOR)
    return float(confidence)


def _build_prompt(product, categories):
    """Construct the classification prompt over the full taxonomy."""
    category_lines = [
        f"  - id: {cat.id} | {cat.full_path}" for cat in categories
    ]
    category_block = "\n".join(category_lines)

    image_note = ""
    if _has_image(product):
        image_note = (
            "\nProduct image URL: "
            f"{product.images.first().url}\n"
            "(Use this for visual context if helpful, but base your "
            "classification primarily on the text fields.)"
        )

    return f"""You are a product classification engine for an e-commerce taxonomy.

Given the following product information and taxonomy, classify the product
into the single best category.

## Product Information
- Title: {product.title or "(none)"}
- Description: {product.description or "(none)"}
- Brand: {product.brand or "(none)"}
- Product type: {product.product_type or "(none)"}{image_note}

## Taxonomy Categories
{category_block}

## Response Format
Respond with ONLY a JSON object matching this exact schema, no markdown,
no explanation outside the JSON:

{{
  "chosen_category_id": <integer, must be one of the ids listed above>,
  "alternatives": [
    {{"category_id": <integer>, "confidence": <float 0-100>}}
  ],
  "attributes": [
    {{"name": "<attribute name>", "value": "<attribute value>"}}
  ],
  "confidence": <float 0-100>,
  "reasoning": "<one sentence explaining why this category was chosen>"
}}

Rules:
- chosen_category_id MUST be one of the ids above.
- confidence is a percentage from 0 to 100.
- alternatives should list 1-3 other plausible categories in descending
  confidence order (can be empty if nothing else is plausible).
- attributes should reflect observable product traits (color, material,
  size, etc.) based on the text provided. Use empty list if unknown.
- reasoning is for internal audit only, keep it under 20 words."""


def _parse_and_validate(response_text, valid_ids):
    """Parse the AI response JSON and validate constraints."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ClassificationParseError(
            f"AI response is not valid JSON: {exc}",
            raw_response=response_text,
        )

    if not isinstance(data, dict):
        raise ClassificationParseError(
            "AI response is not a JSON object",
            raw_response=response_text,
        )

    chosen_id = data.get("chosen_category_id")
    if chosen_id is None:
        raise ClassificationParseError(
            "AI response missing 'chosen_category_id'",
            raw_response=response_text,
        )
    if chosen_id not in valid_ids:
        raise ClassificationParseError(
            f"AI chose category_id {chosen_id} which is not in the taxonomy",
            raw_response=response_text,
        )

    confidence = data.get("confidence")
    if confidence is None or not isinstance(confidence, (int, float)):
        raise ClassificationParseError(
            "AI response missing or non-numeric 'confidence'",
            raw_response=response_text,
        )
    if not 0 <= confidence <= 100:
        raise ClassificationParseError(
            f"AI confidence {confidence} is out of range 0-100",
            raw_response=response_text,
        )

    alternatives = data.get("alternatives", [])
    if not isinstance(alternatives, list):
        alternatives = []

    attributes = data.get("attributes", [])
    if not isinstance(attributes, list):
        attributes = []

    reasoning = str(data.get("reasoning", "") or "")

    return {
        "chosen_category_id": chosen_id,
        "alternatives": alternatives,
        "attributes": attributes,
        "confidence": float(confidence),
        "reasoning": reasoning,
    }


def classify_product(product):
    """Classify a product with the AI model against the full taxonomy.

    Returns the parsed result dict with 'confidence' already adjusted for
    data completeness.
    """
    from taxonomy.services.cache import get_all_categories

    categories = get_all_categories()
    valid_ids = {cat.id for cat in categories}

    prompt = _build_prompt(product, categories)
    response_text = call_ai(prompt)
    result = _parse_and_validate(response_text, valid_ids)
    result["confidence"] = adjust_confidence(product, result["confidence"])
    return result
