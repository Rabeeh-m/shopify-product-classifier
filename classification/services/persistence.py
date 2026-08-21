import logging

from django.conf import settings
from django.db import transaction

from classification.models import Classification, ClassificationAttribute
from taxonomy.models import Attribute, AttributeValue

logger = logging.getLogger(__name__)


def _resolve_attribute(ai_attr, attr_map, value_map):
    """Resolve an AI attribute dict using pre-loaded lookup maps.

    Args:
        ai_attr: Dict with optional 'name' and 'value' keys.
        attr_map: {lowercase attribute name: Attribute} pre-loaded once per
            save so N attributes don't cost N queries.
        value_map: {(attribute_id, lowercase value): AttributeValue}.

    Returns:
        (attribute_obj_or_None, value_obj_or_None, free_text_value_str)
    """
    attr_name = str(ai_attr.get("name", "") or "").strip()
    raw_value = str(ai_attr.get("value", "") or "").strip()

    if not attr_name:
        return None, None, ""

    attr_obj = attr_map.get(attr_name.lower())
    if attr_obj is None:
        attr_obj = Attribute.objects.create(name=attr_name)
        attr_map[attr_name.lower()] = attr_obj

    value_obj = None
    free_text = ""
    if raw_value:
        value_obj = value_map.get((attr_obj.id, raw_value.lower()))
        if value_obj is None:
            free_text = raw_value

    return attr_obj, value_obj, free_text


def _load_attribute_maps():
    """Load all Attributes and AttributeValues in two queries.

    Both tables are small taxonomy-wide reference data, so loading them
    wholesale per classification is far cheaper than per-attribute lookups.
    """
    attr_map = {a.name.lower(): a for a in Attribute.objects.all()}
    value_map = {
        (v.attribute_id, v.value.lower()): v
        for v in AttributeValue.objects.select_related("attribute")
    }
    return attr_map, value_map


def _get_category(category_id):
    """Resolve a category by id from the cached taxonomy, falling back to DB."""
    from taxonomy.models import Category
    from taxonomy.services.cache import get_all_categories

    for cat in get_all_categories():
        if cat.id == category_id:
            return cat
    return Category.objects.get(id=category_id)


def save_classification(product, ai_response, final_confidence):
    """Persist the classification result in one atomic transaction.

    Creates or updates:
      - Classification row (category, confidence, alternatives, status)
      - ClassificationAttribute rows (resolving to existing values where
        possible, otherwise storing free_text_value)
      - Product.status mirror

    Args:
        product: Product instance to classify.
        ai_response: Parsed dict from classifier.py (chosen_category_id,
            alternatives, attributes, confidence, reasoning).
        final_confidence: Adjusted confidence float from
            confidence.calculate_confidence().

    Returns:
        The saved Classification instance.

    Raises:
        ValueError if chosen_category_id is missing.
    """
    chosen_id = ai_response.get("chosen_category_id")
    if chosen_id is None:
        raise ValueError("ai_response missing 'chosen_category_id'")

    category = _get_category(chosen_id)
    alternatives = ai_response.get("alternatives", [])
    ai_attributes = ai_response.get("attributes", [])

    threshold = getattr(settings, "CLASSIFICATION_CONFIDENCE_THRESHOLD", 70)
    if final_confidence >= threshold:
        # High confidence: auto-approve so it never enters the review queue.
        classification_status = Classification.Status.APPROVED
        product_status = "done"
    else:
        classification_status = Classification.Status.NEEDS_REVIEW
        product_status = "needs_review"

    attr_map, value_map = _load_attribute_maps()
    resolved_attributes = []
    for ai_attr in ai_attributes:
        attr_obj, value_obj, free_text = _resolve_attribute(
            ai_attr, attr_map, value_map
        )
        if attr_obj is None:
            continue
        resolved_attributes.append(
            {
                "attribute": attr_obj,
                "value": value_obj,
                "free_text_value": free_text,
            }
        )

    with transaction.atomic():
        classification, _created = Classification.objects.update_or_create(
            product=product,
            defaults={
                "category": category,
                "confidence": final_confidence,
                "alternatives": alternatives,
                "status": classification_status,
            },
        )

        # Replace all attributes atomically
        classification.attributes.all().delete()
        for attrs in resolved_attributes:
            ClassificationAttribute.objects.create(
                classification=classification, **attrs
            )

        # Mirror status onto the product
        product.status = product_status
        product.save(update_fields=["status", "updated_at"])

    logger.info(
        "Saved classification for '%s': category=%s, confidence=%.1f, "
        "status=%s, product.status=%s",
        product.title,
        category.full_path,
        final_confidence,
        classification_status,
        product_status,
    )
    return classification
