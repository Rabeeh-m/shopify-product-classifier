import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone as tz

from products.models import Product

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Requeue products stuck in 'processing' status. "
        "Respects retry_count against CLASSIFICATION_MAX_RETRIES."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=30,
            help="Minutes after which a product is considered stuck (default: 30).",
        )

    def handle(self, *args, **options):
        minutes = options["older_than_minutes"]
        cutoff = tz.now() - timedelta(minutes=minutes)
        max_retries = self._get_max_retries()

        stuck = Product.objects.filter(
            status=Product.Status.PROCESSING,
            processing_started_at__lt=cutoff,
        )

        requeued = 0
        permanently_failed = 0

        for product in stuck.select_for_update(skip_locked=True):
            if product.retry_count >= max_retries:
                product.status = Product.Status.FAILED
                product.processing_started_at = None
                product.error_message = (
                    f"Permanently failed: exceeded max retries ({max_retries})"
                )
                product.save(
                    update_fields=[
                        "status",
                        "processing_started_at",
                        "error_message",
                    ]
                )
                permanently_failed += 1
                logger.warning(
                    "Product %d (%s) permanently failed: retry_count=%d >= %d",
                    product.id,
                    product.title,
                    product.retry_count,
                    max_retries,
                )
            else:
                product.status = Product.Status.PENDING
                product.processing_started_at = None
                product.retry_count += 1
                product.save(
                    update_fields=[
                        "status",
                        "processing_started_at",
                        "retry_count",
                    ]
                )
                requeued += 1
                logger.info(
                    "Product %d (%s) requeued (retry %d/%d)",
                    product.id,
                    product.title,
                    product.retry_count,
                    max_retries,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Requeued: {requeued}, permanently failed: {permanently_failed}"
            )
        )

    def _get_max_retries(self):
        from django.conf import settings

        return getattr(settings, "CLASSIFICATION_MAX_RETRIES", 3)
