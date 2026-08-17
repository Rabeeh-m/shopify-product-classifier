from django.db import models


class Product(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        NEEDS_REVIEW = "needs_review", "Needs Review"
        FAILED = "failed", "Failed"

    external_id = models.CharField(max_length=255, db_index=True)
    title = models.CharField(max_length=512)
    description = models.TextField(blank=True, default="")
    brand = models.CharField(max_length=255, blank=True, default="")
    product_type = models.CharField(max_length=255, blank=True, default="")
    raw_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="images"
    )
    url = models.URLField(max_length=1024)
    is_valid = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.url
