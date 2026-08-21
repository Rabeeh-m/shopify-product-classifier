"""Rule-based product classification before AI fallback.

Tries vendor import mappings and high-confidence keyword matches first.
Returns a classification dict compatible with save_classification(), or None
when rules are not confident enough (caller should invoke AI).
"""

import logging
import re

from django.conf import settings

from classification.data.vendor_category_rules import VENDOR_SUBCATEGORY_RULES

logger = logging.getLogger(__name__)

# Raw import columns whose text is allowed to influence *title* rule matching.
# The vendor sub-category/category columns are deliberately excluded: their
# values (e.g. "Sofas and Armchairs") would otherwise match their own keywords
# and defeat within-sub-category disambiguation.
_RAW_TEXT_KEYS = (
    "bullets",
    "set_includes",
    "materials",
    "material",
)


def _normalize_key(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _get_search_text(product):
    """Combine product fields used for vendor title-rule matching."""
    parts = [
        product.title or "",
        product.description or "",
    ]
    raw = getattr(product, "raw_data", None) or {}
    for key in _RAW_TEXT_KEYS:
        val = raw.get(key)
        if val:
            parts.append(str(val))
    return " ".join(parts).lower()


def _get_vendor_sub_category(product):
    raw = getattr(product, "raw_data", None) or {}
    for key in ("product_sub_category", "product_category"):
        val = raw.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return (product.product_type or "").strip()


def _build_category_lookup(categories):
    return {cat.name.lower(): cat for cat in categories}


def _resolve_category(category_name, category_by_name):
    if not category_name:
        return None
    return category_by_name.get(category_name.lower())


def _title_matches(text, keywords):
    return any(keyword in text for keyword in keywords)


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


def _build_result(category, confidence, reasoning, *, product, alternatives=None):
    return {
        "chosen_category_id": category.id,
        "alternatives": alternatives or [],
        "attributes": _extract_attributes(product),
        "confidence": float(confidence),
        "reasoning": f"[rules] {reasoning}",
    }


def _try_vendor_rules(product, category_by_name):
    vendor_sub = _normalize_key(_get_vendor_sub_category(product))
    if not vendor_sub:
        return None

    rule = VENDOR_SUBCATEGORY_RULES.get(vendor_sub)
    if rule is None:
        return None

    text = _get_search_text(product)
    confidence = float(getattr(settings, "RULE_VENDOR_CONFIDENCE", 90))

    if isinstance(rule, str):
        category = _resolve_category(rule, category_by_name)
        if category is None:
            return None
        return _build_result(
            category,
            confidence,
            f"Vendor sub-category '{vendor_sub}' maps to '{category.name}'",
            product=product,
        )

    title_rules = rule.get("title_rules") or ()
    for keywords, category_name in title_rules:
        if not _title_matches(text, keywords):
            continue
        category = _resolve_category(category_name, category_by_name)
        if category is None:
            continue
        matched = ", ".join(keywords)
        return _build_result(
            category,
            confidence,
            (
                f"Vendor sub-category '{vendor_sub}' + title match "
                f"({matched}) → '{category.name}'"
            ),
            product=product,
        )

    default_name = rule.get("default")
    if default_name:
        category = _resolve_category(default_name, category_by_name)
        if category is not None:
            return _build_result(
                category,
                confidence,
                (
                    f"Vendor sub-category '{vendor_sub}' has no stronger "
                    f"title match → default '{category.name}'"
                ),
                product=product,
            )

    return None


def _try_keyword_auto_pick(product, candidates):
    if not candidates:
        return None

    min_score = float(getattr(settings, "RULE_AUTO_CLASSIFY_MIN_SCORE", 6.0))
    min_gap = float(getattr(settings, "RULE_MIN_SCORE_GAP", 2.0))
    base_confidence = float(getattr(settings, "RULE_KEYWORD_CONFIDENCE_BASE", 70))

    top = candidates[0]
    if top.score < min_score:
        return None

    second_score = candidates[1].score if len(candidates) > 1 else 0.0
    if second_score and (top.score - second_score) < min_gap:
        return None

    confidence = min(95.0, base_confidence + top.score * 2)
    alternatives = []
    for candidate in candidates[1:4]:
        if candidate.category.id == top.category.id:
            continue
        alt_conf = max(10.0, confidence - (top.score - candidate.score) * 5)
        alternatives.append(
            {"category_id": candidate.category.id, "confidence": round(alt_conf, 1)}
        )

    return _build_result(
        top.category,
        confidence,
        (
            f"Keyword score {top.score:.1f} for '{top.category.name}' "
            f"(gap vs #2: {top.score - second_score:.1f})"
        ),
        product=product,
        alternatives=alternatives,
    )


def try_rule_classification(product, candidates):
    """Return a classification dict if rules are confident, else None."""
    if not getattr(settings, "RULE_CLASSIFICATION_ENABLED", True):
        return None

    from taxonomy.services.cache import get_all_categories

    categories = get_all_categories()
    category_by_name = _build_category_lookup(categories)

    result = _try_vendor_rules(product, category_by_name)
    if result is not None:
        logger.info(
            "Rule classification for '%s': %s",
            product.title,
            result["reasoning"],
        )
        return result

    result = _try_keyword_auto_pick(product, candidates)
    if result is not None:
        logger.info(
            "Keyword auto-classification for '%s': %s",
            product.title,
            result["reasoning"],
        )
        return result

    return None
