import logging

from django.conf import settings
from django.db import transaction

from classification.models import Classification, ClassificationAttribute
from taxonomy.models import Attribute, AttributeValue, Category

logger = logging.getLogger(__name__)


def _resolve_attribute(ai_attr, allowed_attribute_ids=None):
    """Resolve an AI attribute dict to (attribute, value_or_None, free_text).

    When ``allowed_attribute_ids`` is given, attributes not in that set are
    discarded (returned as None) so only attributes relevant to the chosen
    category are persisted.
    """
    attr_name = str(ai_attr.get("name", "") or "").strip()
    raw_value = str(ai_attr.get("value", "") or "").strip()

    if not attr_name:
        return None, None, ""

    attr_obj = Attribute.objects.filter(name__iexact=attr_name).first()
    if attr_obj is None:
        if allowed_attribute_ids is not None:
            return None, None, ""
        attr_obj = Attribute.objects.create(name=attr_name)

    if allowed_attribute_ids is not None and attr_obj.id not in allowed_attribute_ids:
        return None, None, ""

    value_obj = None
    free_text = ""
    if raw_value:
        value_obj = AttributeValue.objects.filter(
            attribute=attr_obj, value__iexact=raw_value
        ).first()
        if value_obj is None:
            free_text = raw_value

    return attr_obj, value_obj, free_text


def save_classification(product, result, source=Classification.Source.AI):
    """Persist a classification result and mirror status onto the product.

    Results at or above CLASSIFICATION_CONFIDENCE_THRESHOLD are auto-approved;
    anything lower lands in the review queue.
    """
    chosen_id = result.get("chosen_category_id")
    if chosen_id is None:
        raise ValueError("result missing 'chosen_category_id'")

    category = Category.objects.get(id=chosen_id)
    confidence = float(result.get("confidence", 0.0))
    threshold = getattr(settings, "CLASSIFICATION_CONFIDENCE_THRESHOLD", 70)

    if confidence >= threshold:
        classification_status = Classification.Status.APPROVED
        product_status = "done"
    else:
        classification_status = Classification.Status.NEEDS_REVIEW
        product_status = "needs_review"

    # Only persist attributes that are valid for the chosen category.
    allowed_attribute_ids = set(
        category.category_attributes.values_list("attribute_id", flat=True)
    )

    resolved_attributes = []
    for ai_attr in result.get("attributes", []):
        attr_obj, value_obj, free_text = _resolve_attribute(
            ai_attr, allowed_attribute_ids=allowed_attribute_ids
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
                "source": source,
                "category": category,
                "confidence": confidence,
                "alternatives": result.get("alternatives", []),
                "status": classification_status,
            },
        )

        classification.attributes.all().delete()
        for attrs in resolved_attributes:
            ClassificationAttribute.objects.create(
                classification=classification, **attrs
            )

        product.status = product_status
        product.save(update_fields=["status", "updated_at"])

    logger.info(
        "Saved classification for '%s': category=%s, confidence=%.1f, status=%s",
        product.title,
        category.full_path,
        confidence,
        classification_status,
    )
    return classification
