"""Vendor sub-category → Shopify taxonomy leaf mapping.

A plain exact-match dict: the import sheet's product_sub_category column
is normalized (lowercase, collapsed whitespace) and looked up here.
Only unambiguous sub-categories are mapped — genuinely mixed ones
("tables", "decor", "bar and dining") are left to the AI so a guess
never overrides a better classification.
"""

import logging
import re

logger = logging.getLogger(__name__)

VENDOR_RULE_CONFIDENCE = 90.0

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


def try_rule_classification(product):
    """Return a classification dict if the vendor mapping hits, else None."""
    from taxonomy.services.cache import get_all_categories

    vendor_sub = _normalize(get_vendor_sub_category(product))
    category_name = VENDOR_CATEGORY_MAP.get(vendor_sub)
    if not category_name:
        return None

    for cat in get_all_categories():
        if cat.name.lower() == category_name.lower():
            logger.info(
                "Rule classification for '%s': %s → %s",
                product.title,
                vendor_sub,
                category_name,
            )
            return {
                "chosen_category_id": cat.id,
                "alternatives": [],
                "attributes": _extract_attributes(product),
                "confidence": VENDOR_RULE_CONFIDENCE,
                "reasoning": f"[rules] Vendor sub-category '{vendor_sub}'",
            }

    # Mapped but the loaded taxonomy doesn't have that leaf (e.g. an older
    # taxonomy snapshot) — let the AI decide instead of failing the product.
    logger.warning(
        "Rule target '%s' not in taxonomy; falling back to AI for '%s'",
        category_name,
        product.title,
    )
    return None
