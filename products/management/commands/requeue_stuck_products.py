import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone as tz

from products.models import Product

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Requeue products stuck in 'processing' status (or marked 'failed') "
        "back to pending."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=30,
            help="Minutes after which a product is considered stuck (default: 30).",
        )
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help=(
                "Also requeue products in 'failed' status "
                "(e.g. after a rate-limit outage)."
            ),
        )

    def handle(self, *args, **options):
        minutes = options["older_than_minutes"]
        include_failed = options["include_failed"]
        cutoff = tz.now() - timedelta(minutes=minutes)

        if include_failed:
            queryset = Product.objects.filter(
                status__in=[Product.Status.PROCESSING, Product.Status.FAILED]
            ).exclude(
                status=Product.Status.PROCESSING,
                processing_started_at__gt=cutoff,
            )
        else:
            queryset = Product.objects.filter(
                status=Product.Status.PROCESSING,
                processing_started_at__lt=cutoff,
            )

        requeued = 0

        for product in queryset.select_for_update(skip_locked=True).iterator():
            product.status = Product.Status.PENDING
            product.processing_started_at = None
            product.error_message = ""
            product.save(
                update_fields=["status", "processing_started_at", "error_message"]
            )
            requeued += 1
            logger.info("Product %d (%s) requeued", product.id, product.title)

        self.stdout.write(
            self.style.SUCCESS(f"Requeued: {requeued}")
        )
