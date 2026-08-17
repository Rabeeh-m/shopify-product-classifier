import json
import logging

from classification.exceptions import ClassificationParseError
from classification.services.ai_client import call_ai

logger = logging.getLogger(__name__)


def _build_prompt(product, candidates):
    """Construct the classification prompt for the AI model.

    Kept as a pure function for easy review and tuning without
    changing calling or parsing logic.
    """
    candidate_lines = []
    for cr in candidates:
        cat = cr.category
        candidate_lines.append(
            f"  - id: {cat.id}\n"
            f"    name: {cat.name}\n"
            f"    full_path: {cat.full_path}\n"
            f"    keyword_score: {cr.score:.2f}"
        )
    candidate_block = "\n".join(candidate_lines)

    image_note = ""
    if hasattr(product, "images"):
        first_img = product.images.first()
        if first_img and first_img.url:
            image_note = (
                f"\nProduct image URL: {first_img.url}\n"
                "(Use this for visual context if helpful, but base your "
                "classification primarily on the text fields.)"
            )

    return f"""You are a product classification engine for an e-commerce taxonomy.

Given the following product information and a list of candidate categories,
classify the product into the single best category.

## Product Information
- Title: {product.title or "(none)"}
- Description: {product.description or "(none)"}
- Brand: {product.brand or "(none)"}
- Product type: {product.product_type or "(none)"}{image_note}

## Candidate Categories
{candidate_block}

## Response Format
Respond with ONLY a JSON object matching this exact schema, no markdown,
no explanation outside the JSON:

{{
  "chosen_category_id": <integer, must be one of the candidate ids listed above>,
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
- chosen_category_id MUST be one of the candidate ids above.
- confidence is a percentage from 0 to 100.
- alternatives should list 1-3 other plausible categories in descending
  confidence order (can be empty if nothing else is plausible).
- attributes should reflect observable product traits (color, material,
  size, etc.) based on the text provided. Use empty list if unknown.
- reasoning is for internal audit only, keep it under 20 words."""


def _parse_and_validate(response_text, candidate_ids):
    """Parse the AI response JSON and validate constraints.

    Returns the parsed dict on success.
    Raises ClassificationParseError on any validation failure.
    """
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
    if chosen_id not in candidate_ids:
        raise ClassificationParseError(
            f"AI chose category_id {chosen_id} which is not in the "
            f"candidate list {candidate_ids}",
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
        raise ClassificationParseError(
            "'alternatives' must be a list",
            raw_response=response_text,
        )

    attributes = data.get("attributes", [])
    if not isinstance(attributes, list):
        raise ClassificationParseError(
            "'attributes' must be a list",
            raw_response=response_text,
        )

    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)

    return {
        "chosen_category_id": chosen_id,
        "alternatives": alternatives,
        "attributes": attributes,
        "confidence": float(confidence),
        "reasoning": reasoning,
    }


def classify_product(product, candidates):
    """Classify a product using the AI model against narrowed candidates.

    Args:
        product: A Product instance (with title, description, brand,
            product_type, and optionally a images reverse relation).
        candidates: A list of CandidateResult namedtuples from
            candidate_finder.find_candidates(). Each has .category
            (Category model instance) and .score.

    Returns:
        A dict with keys: chosen_category_id, alternatives, attributes,
        confidence, reasoning.

    Raises:
        ClassificationParseError on model output validation failure.
        AIClientError on API/network failures (after retries exhausted).
    """
    if not candidates:
        raise ClassificationParseError("No candidates provided for classification")

    candidate_ids = {cr.category.id for cr in candidates}
    prompt = _build_prompt(product, candidates)

    response_text = call_ai(prompt)
    return _parse_and_validate(response_text, candidate_ids)
