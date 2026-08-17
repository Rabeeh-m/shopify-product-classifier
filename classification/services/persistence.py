import logging

from django.conf import settings
from django.db import transaction

from classification.models import Classification, ClassificationAttribute
from taxonomy.models import Attribute, AttributeValue

logger = logging.getLogger(__name__)


def _resolve_attribute(ai_attr):
    """Resolve an AI attribute dict to (Attribute, AttributeValue | None, str).

    Looks up the attribute by name (case-insensitive).  Then tries to
    match the value to an existing AttributeValue for that attribute
    (case-insensitive).

    Returns:
        (attribute_obj, value_obj_or_None, free_text_value_str)
    """
    attr_name = ai_attr.get("name", "").strip()
    raw_value = ai_attr.get("value", "").strip()

    if not attr_name:
        return None, None, ""

    # Resolve attribute (case-insensitive)
    attr_obj = Attribute.objects.filter(
        name__iexact=attr_name
    ).first() or Attribute.objects.create(name=attr_name)

    # Resolve value (case-insensitive within the attribute)
    value_obj = None
    free_text = ""
    if raw_value:
        value_obj = AttributeValue.objects.filter(
            attribute=attr_obj, value__iexact=raw_value
        ).first()
        if value_obj is None:
            free_text = raw_value

    return attr_obj, value_obj, free_text


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
    from taxonomy.models import Category

    chosen_id = ai_response.get("chosen_category_id")
    if chosen_id is None:
        raise ValueError("ai_response missing 'chosen_category_id'")

    category = Category.objects.get(id=chosen_id)
    alternatives = ai_response.get("alternatives", [])
    ai_attributes = ai_response.get("attributes", [])

    threshold = getattr(settings, "CLASSIFICATION_CONFIDENCE_THRESHOLD", 70)
    if final_confidence >= threshold:
        classification_status = Classification.Status.NEEDS_REVIEW
        product_status = "done"
    else:
        classification_status = Classification.Status.NEEDS_REVIEW
        product_status = "needs_review"

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
        for ai_attr in ai_attributes:
            attr_obj, value_obj, free_text = _resolve_attribute(ai_attr)
            if attr_obj is None:
                continue
            ClassificationAttribute.objects.create(
                classification=classification,
                attribute=attr_obj,
                value=value_obj,
                free_text_value=free_text,
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
