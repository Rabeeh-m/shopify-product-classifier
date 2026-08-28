import json
import logging

from classification.exceptions import ClassificationParseError
from classification.services.ai_client import call_ai
from taxonomy.services.hierarchy import get_children, get_root_categories

logger = logging.getLogger(__name__)

# Data-completeness adjustments to the AI's reported confidence:
#   title only → cap 50, no description → cap 65, no image → -5 (floor 30).
_TITLE_ONLY_CAP = 50.0
_NO_DESCRIPTION_CAP = 65.0
_NO_IMAGE_PENALTY = 5.0
_NO_IMAGE_FLOOR = 30.0

# Hard cap on how many tree levels we descend, guarding against a looping
# model. The deepest Shopify category is ~8 levels.
_MAX_DEPTH = 10


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


def _product_block(product):
    image_note = ""
    if _has_image(product):
        image_note = (
            "\nProduct image URL: "
            f"{product.images.first().url}\n"
            "(Use this for visual context if helpful, but base your "
            "classification primarily on the text fields.)"
        )
    return (
        f"## Product Information\n"
        f"- Title: {product.title or '(none)'}\n"
        f"- Description: {product.description or '(none)'}\n"
        f"- Brand: {product.brand or '(none)'}\n"
        f"- Product type: {product.product_type or '(none)'}{image_note}"
    )


def _candidate_lines(candidates):
    lines = []
    for cat in candidates:
        leaf = " (leaf)" if not getattr(cat, "children", None) else ""
        lines.append(f"  - id: {cat.id} | {cat.name}{leaf}")
    return "\n".join(lines)


def _build_step_prompt(product, path, candidates):
    """Prompt to pick the best sub-category among ``candidates``."""
    path_str = " > ".join(path) if path else "(top level)"
    return f"""You are a product classification engine for an e-commerce taxonomy.

Given the following product information, choose the single best category from
the candidates listed below. The candidates are sub-categories that belong
under "{path_str}".

{_product_block(product)}

## Candidate Categories
{_candidate_lines(candidates)}

## Response Format
Respond with ONLY a JSON object matching this exact schema, no markdown:
{{
  "chosen_category_id": <integer, one of the ids listed above>,
  "confidence": <float 0-100>,
  "reasoning": "<one sentence (under 20 words)>"
}}

Rules:
- chosen_category_id MUST be one of the ids listed above.
- Choose the candidate that best fits the product. If the product belongs in
  a more specific descendant of one candidate, still pick that candidate — we
  will narrow down in the next step.
- confidence is a percentage from 0 to 100."""


def _build_attributes_prompt(product, category, attrs_with_values):
    """Prompt to fill in the allowed attributes for a chosen category."""
    lines = []
    for name, values in attrs_with_values:
        if values:
            lines.append(f"  - {name}: {{{', '.join(values)}}}")
        else:
            lines.append(f"  - {name}: (free text)")
    attrs_block = "\n".join(lines)

    return f"""You are an attribute extraction engine for an e-commerce taxonomy.

The product below was classified into this category:
{category.full_path}

Fill in the attributes that are RELEVANT to this product using ONLY the
allowed attributes and their allowed values listed below. If an attribute
cannot be determined from the product, omit it.

{_product_block(product)}

## Allowed Attributes for "{category.name}"
{attrs_block}

## Response Format
Respond with ONLY a JSON object matching this exact schema, no markdown:
{{
  "attributes": [
    {{"name": "<attribute name, must be one allowed above>",
      "value": "<one of the allowed values, or a short free-text value>"}}
  ]
}}

Rules:
- attribute "name" MUST match one of the allowed attribute names exactly.
- Prefer one of the allowed values; fall back to free text only if none fits.
- Return an empty array if no attributes are determinable."""


def _parse_step(response_text):
    """Parse and validate a single descent-step AI response."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ClassificationParseError(
            f"AI response is not valid JSON: {exc}", raw_response=response_text
        )

    if not isinstance(data, dict):
        raise ClassificationParseError(
            "AI response is not a JSON object", raw_response=response_text
        )

    chosen_id = data.get("chosen_category_id")
    if chosen_id is None:
        raise ClassificationParseError(
            "AI response missing 'chosen_category_id'", raw_response=response_text
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

    return {
        "chosen_category_id": chosen_id,
        "confidence": float(confidence),
        "reasoning": str(data.get("reasoning", "") or ""),
        "alternatives": alternatives,
    }


def _parse_attributes(response_text, allowed_names):
    """Parse and validate the attribute-extraction AI response."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ClassificationParseError(
            f"AI response is not valid JSON: {exc}", raw_response=response_text
        )

    if not isinstance(data, dict):
        raise ClassificationParseError(
            "AI response is not a JSON object", raw_response=response_text
        )

    raw_attrs = data.get("attributes", [])
    if not isinstance(raw_attrs, list):
        raw_attrs = []

    attributes = []
    for item in raw_attrs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        value = str(item.get("value", "") or "").strip()
        if not name:
            continue
        attributes.append({"name": name, "value": value})

    return {"attributes": attributes}


def _select_hierarchical(product):
    """Walk the category tree from the roots down to a leaf.

    Returns (category, result_dict) where result_dict matches the public
    contract (chosen_category_id, alternatives, attributes, confidence,
    reasoning).
    """
    path = []
    current_candidates = get_root_categories()
    current_path = path
    chosen = None
    step_count = 0
    last_result = None

    while True:
        if not current_candidates:
            raise ClassificationParseError(
                "No candidate categories available to classify into."
            )
        if step_count >= _MAX_DEPTH:
            # Stop descending and accept the deepest candidate as the leaf.
            if chosen is None:
                chosen = current_candidates[0]
            break

        prompt = _build_step_prompt(product, current_path, current_candidates)
        result = _parse_step(call_ai(prompt))
        last_result = result

        valid_ids = {c.id for c in current_candidates}
        chosen_id = result["chosen_category_id"]
        if chosen_id not in valid_ids:
            raise ClassificationParseError(
                f"AI chose category_id {chosen_id} which is not among the "
                "candidates",
                raw_response=prompt,
            )

        next_candidates = [c for c in current_candidates if c.id == chosen_id]
        chosen = next_candidates[0]
        children = get_children(chosen)

        path.append(chosen.name)
        step_count += 1

        if not children:
            break  # reached a leaf
        current_candidates = children
        current_path = path

    alternatives = last_result.get("alternatives", []) if last_result else []
    return chosen, last_result, alternatives, step_count


def _attribute_options(category):
    """Return [(attribute_name, [allowed values])] for a category."""
    from taxonomy.models import Attribute

    qs = (
        Attribute.objects.filter(category_attributes__category=category)
        .prefetch_related("values")
        .order_by("name")
    )
    options = []
    for attr in qs:
        values = [v.value for v in attr.values.all()]
        options.append((attr.name, values))
    return options


def _extract_attributes(product, category, allowed_names):
    """Run attribute extraction constrained to the category's allowed attrs.

    Returns a list of {"name", "value"} dicts.
    """
    options = _attribute_options(category)
    options = [(n, v) for n, v in options if n in allowed_names] or options

    attrs_with_values = [(n, v) for n, v in options]
    prompt = _build_attributes_prompt(product, category, attrs_with_values)
    result = _parse_attributes(call_ai(prompt), {n for n, _ in options})

    # Only keep attributes that are allowed for the category.
    allowed = {n for n, _ in options}
    kept = [
        {"name": a["name"], "value": a["value"]}
        for a in result["attributes"]
        if a["name"] in allowed
    ]
    return kept


def classify_product(product):
    """Classify a product against the full taxonomy.

    Uses hierarchical (top-down) category selection followed by attribute
    extraction constrained to the chosen category's allowed attributes.

    Returns a result dict:
        {chosen_category_id, alternatives, attributes, confidence, reasoning}
    """
    category, last_result, alternatives, _steps = _select_hierarchical(product)
    allowed_names = {name for name, _ in _attribute_options(category)}
    attributes = _extract_attributes(product, category, allowed_names)

    confidence = last_result["confidence"] if last_result else 0.0
    return {
        "chosen_category_id": category.id,
        "alternatives": alternatives,
        "attributes": attributes,
        "confidence": adjust_confidence(product, confidence),
        "reasoning": last_result["reasoning"] if last_result else "",
    }
