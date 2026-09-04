"""Vendor sub-category → Shopify taxonomy leaf mapping.

The import sheet's product_sub_category column is normalized (lowercase,
collapsed whitespace) and resolved to a taxonomy leaf. Resolution is layered:

1. Exact match against the map — deterministic, zero cost.
2. Fuzzy match via rapidfuzz for near-misses (typos, plurals, extra/missing
   words). To keep wrong-category risk low, the fuzzy path is conservative:
   - a high absolute similarity threshold, AND
   - the best match must clearly beat the next-best (a gap), so a value that
     sits between two plausible categories is NOT guessed.
3. Falls back to the AI when there is no confident match.

Genuinely mixed / ambiguous sub-categories ("tables", "decor") are in
FUZZY_SKIP and are always left to the AI, so a guess never overrides a
better AI classification.
"""

import logging
import re

import rapidfuzz.fuzz as _fuzz

logger = logging.getLogger(__name__)

VENDOR_RULE_CONFIDENCE = 90.0

# Minimum rapidfuzz ratio (0-100) required to accept a fuzzy match. High on
# purpose: we only want near-exact typos/plurals, not loose semantic guesses.
FUZZY_MATCH_THRESHOLD = 85.0

# The best match must beat the second-best by at least this many points.
# Prevents choosing between two close categories — ambiguous values fall back
# to AI (which can reason) instead of a coin-flip guess.
FUZZY_WIN_MARGIN = 8.0

# Sub-categories that are genuinely ambiguous and must never be resolved by
# fuzzy matching. Kept as normalized strings matched against the raw value.
FUZZY_SKIP = {
    "tables",
    "table",
    "decor",
    "decorations",
    "bar and dining",
    "dining",
    "furniture",
    "accessories",
    "lighting",
    "other",
}

VENDOR_CATEGORY_MAP = {
    # Direct mappings — the vendor sub-category always means one Shopify leaf.
    "sofa sectionals": "Sectional Sofas",
    "vanities": "Vanities",
    "dining chairs": "Dining Chairs",
    "bar and dining tables": "Dining Tables",
    "bar and counter stools": "Bar Stools",
    "ceiling lamps": "Ceiling Lights",
    "table lamps": "Table Lamps",
    "floor lamps": "Floor Lamps",
    "office chairs": "Office Chairs",
    "benches and stools": "Benches",
    "computer desks": "Desk Tables",
    "pillow": "Throw Pillows",
    # Dominant-type defaults for mildly ambiguous sub-categories.
    "sofas and armchairs": "Sofas",
    "daybeds and lounges": "Daybeds",
    "dining sets": "Dining Sets",
}


def _normalize(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def get_vendor_sub_category(product):
    raw = getattr(product, "raw_data", None) or {}
    for key in ("product_sub_category", "product_category"):
        val = raw.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return (product.product_type or "").strip()


def _extract_attributes(product):
    """Pull obvious attributes from normalized import row data."""
    raw = getattr(product, "raw_data", None) or {}
    attrs = []

    color = raw.get("product_color") or raw.get("color")
    if color and str(color).strip():
        attrs.append({"name": "Color", "value": str(color).strip()})

    material = raw.get("materials") or raw.get("material")
    if material and str(material).strip():
        attrs.append({"name": "Material", "value": str(material).strip()})

    return attrs


def _fuzzy_match_key(vendor_sub):
    """Return a map key for a normalized vendor sub-category.

    Exact matches are tried first; only if there is no exact hit do we fall
    back to fuzzy matching against all non-skipped keys.
    """
    if not vendor_sub or vendor_sub in FUZZY_SKIP:
        return None
    return vendor_sub


def _resolve_category_name(product, vendor_sub):
    """Resolve vendor sub-category → taxonomy leaf name, exact then fuzzy.

    Returns (category_name, via_fuzzy) or (None, False). The fuzzy path is
    deliberately conservative (threshold + win margin) to keep wrong-category
    risk low; anything ambiguous falls through to the AI.
    """
    # 1) Exact match.
    name = VENDOR_CATEGORY_MAP.get(vendor_sub)
    if name:
        return name, False

    # 2) Fuzzy match against all resolvable keys.
    if _fuzzy_match_key(vendor_sub) is None:
        return None, False

    candidates = [
        (key, _fuzz.ratio(vendor_sub, key))
        for key in VENDOR_CATEGORY_MAP
        if _fuzzy_match_key(key) is not None
    ]
    if not candidates:
        return None, False

    candidates.sort(key=lambda item: item[1], reverse=True)
    best_key, best_score = candidates[0]

    # Must clear the high absolute threshold AND beat the runner-up by a
    # meaningful margin, otherwise the value is genuinely ambiguous.
    if best_score < FUZZY_MATCH_THRESHOLD:
        return None, False

    second_score = candidates[1][1] if len(candidates) > 1 else 0.0
    if (best_score - second_score) < FUZZY_WIN_MARGIN:
        logger.info(
            "'%s' fuzzy match too close (%.1f vs %.1f); deferring to AI",
            vendor_sub,
            best_score,
            second_score,
        )
        return None, False

    return VENDOR_CATEGORY_MAP[best_key], True


def try_rule_classification(product):
    """Return a classification dict if the vendor mapping hits, else None."""
    from taxonomy.services.cache import get_all_categories

    vendor_sub = _normalize(get_vendor_sub_category(product))
    if not vendor_sub:
        return None

    category_name, via_fuzzy = _resolve_category_name(product, vendor_sub)
    if not category_name:
        return None

    for cat in get_all_categories():
        if cat.name.lower() == category_name.lower():
            match_desc = "fuzzy" if via_fuzzy else "exact"
            logger.info(
                "Rule classification (%s) for '%s': %s → %s",
                match_desc,
                product.title,
                vendor_sub,
                category_name,
            )
            return {
                "chosen_category_id": cat.id,
                "alternatives": [],
                "attributes": _extract_attributes(product),
                "confidence": VENDOR_RULE_CONFIDENCE,
                "reasoning": (
                    f"[rules] Vendor sub-category '{vendor_sub}' ({match_desc})"
                ),
            }

    # Mapped but the loaded taxonomy doesn't have that leaf (e.g. an older
    # taxonomy snapshot) — let the AI decide instead of failing the product.
    logger.warning(
        "Rule target '%s' not in taxonomy; falling back to AI for '%s'",
        category_name,
        product.title,
    )
    return None
