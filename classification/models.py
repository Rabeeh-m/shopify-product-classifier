from django.conf import settings
from django.db import models


class Classification(models.Model):
    class Status(models.TextChoices):
        NEEDS_REVIEW = "needs_review", "Needs Review"
        APPROVED = "approved", "Approved"
        FAILED = "failed", "Failed"

    product = models.OneToOneField(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="classification",
    )
    category = models.ForeignKey(
        "taxonomy.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classifications",
    )
    confidence = models.FloatField()
    alternatives = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEEDS_REVIEW,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classifications_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    correction_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Classification for {self.product}"


class ClassificationAttribute(models.Model):
    classification = models.ForeignKey(
        Classification,
        on_delete=models.CASCADE,
        related_name="attributes",
    )
    attribute = models.ForeignKey(
        "taxonomy.Attribute",
        on_delete=models.CASCADE,
        related_name="classification_attributes",
    )
    value = models.ForeignKey(
        "taxonomy.AttributeValue",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classification_attributes",
    )
    free_text_value = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        unique_together = [("classification", "attribute")]

    def __str__(self):
        val = self.value if self.value else self.free_text_value
        return f"{self.attribute}: {val}"
