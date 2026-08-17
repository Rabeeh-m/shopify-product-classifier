import logging

from django.db import transaction
from django.utils import timezone as tz

from classification.models import Classification, ClassificationAttribute
from taxonomy.models import Attribute, AttributeValue, Category

logger = logging.getLogger(__name__)


class ReviewError(Exception):
    pass


def approve_classification(classification, user):
    """Approve a classification as-is from the AI suggestion.

    Sets status='approved', reviewed_by, reviewed_at, and mirrors
    the product status to 'done'.
    """
    if classification.status != Classification.Status.NEEDS_REVIEW:
        raise ReviewError(
            f"Cannot approve classification in status '{classification.status}'"
        )

    with transaction.atomic():
        classification.status = Classification.Status.APPROVED
        classification.reviewed_by = user
        classification.reviewed_at = tz.now()
        classification.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
        )
        classification.product.status = "done"
        classification.product.save(update_fields=["status", "updated_at"])

    logger.info(
        "Classification %d approved by %s",
        classification.pk,
        user,
    )
    return classification


def correct_classification(classification, user, category_id=None, attributes=None):
    """Correct a classification with an overridden category and/or attributes.

    Args:
        classification: Classification instance (status must be 'needs_review').
        user: The reviewing user.
        category_id: Optional new category ID. Must exist.
        attributes: Optional list of dicts [{"name": str, "value": str}].
            Validates values against the category's allowed attributes.

    Returns:
        The updated Classification instance.

    Raises:
        ReviewError if category doesn't exist, attribute values are invalid,
            or the classification is not in 'needs_review' status.
    """
    if classification.status != Classification.Status.NEEDS_REVIEW:
        raise ReviewError(
            f"Cannot correct classification in status '{classification.status}'"
        )

    new_category = None
    if category_id is not None:
        try:
            new_category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            raise ReviewError(f"Category with id {category_id} does not exist")

    validated_attributes = []
    if attributes is not None:
        cat = new_category or classification.category
        if cat is None:
            raise ReviewError("Cannot validate attributes without a category")
        allowed_attr_ids = set(
            cat.category_attributes.values_list("attribute_id", flat=True)
        )
        for attr_data in attributes:
            name = attr_data.get("name", "").strip()
            value = attr_data.get("value", "").strip()
            if not name:
                continue

            attr_obj = Attribute.objects.filter(name__iexact=name).first()
            if attr_obj is None:
                raise ReviewError(f"Attribute '{name}' does not exist in the taxonomy")
            if attr_obj.id not in allowed_attr_ids:
                raise ReviewError(
                    f"Attribute '{name}' is not valid for category "
                    f"'{cat.full_path}'"
                )

            value_obj = None
            free_text = ""
            if value:
                value_obj = AttributeValue.objects.filter(
                    attribute=attr_obj, value__iexact=value
                ).first()
                if value_obj is None:
                    free_text = value

            validated_attributes.append(
                {
                    "attribute": attr_obj,
                    "value": value_obj,
                    "free_text_value": free_text,
                }
            )

    with transaction.atomic():
        if new_category is not None:
            classification.category = new_category
        classification.status = Classification.Status.APPROVED
        classification.reviewed_by = user
        classification.reviewed_at = tz.now()
        classification.correction_notes = _build_correction_notes(
            classification, new_category, attributes
        )
        classification.save(
            update_fields=[
                "category",
                "status",
                "reviewed_by",
                "reviewed_at",
                "correction_notes",
                "updated_at",
            ]
        )

        if attributes is not None:
            classification.attributes.all().delete()
            for attr_data in validated_attributes:
                ClassificationAttribute.objects.create(
                    classification=classification,
                    **attr_data,
                )

        classification.product.status = "done"
        classification.product.save(update_fields=["status", "updated_at"])

    logger.info(
        "Classification %d corrected by %s: category=%s",
        classification.pk,
        user,
        classification.category,
    )
    return classification


def _build_correction_notes(classification, new_category, attributes):
    """Build a human-readable note about what was changed."""
    parts = []
    old_cat = classification.category
    if new_category is not None and old_cat is not None and new_category != old_cat:
        parts.append(
            f"Category changed from '{old_cat.full_path}' to '{new_category.full_path}'"
        )
    elif new_category is not None and old_cat is None:
        parts.append(f"Category set to '{new_category.full_path}'")
    if attributes is not None:
        parts.append("Attributes updated")
    return "; ".join(parts) if parts else "Approved with corrections"
