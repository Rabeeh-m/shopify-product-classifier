import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as tz

from classification.models import Classification
from products.models import Product

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Auto-approve existing needs_review classifications whose confidence "
        "is at or above CLASSIFICATION_CONFIDENCE_THRESHOLD. Use after "
        "upgrading the auto-approve logic to clean up rows saved by the "
        "old always-needs-review behavior."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--threshold",
            type=float,
            default=None,
            help=(
                "Minimum confidence to auto-approve "
                "(default: settings.CLASSIFICATION_CONFIDENCE_THRESHOLD)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        threshold = options["threshold"]
        if threshold is None:
            threshold = float(
                getattr(settings, "CLASSIFICATION_CONFIDENCE_THRESHOLD", 70)
            )
        dry_run = options["dry_run"]

        candidates = list(
            Classification.objects.filter(
                status=Classification.Status.NEEDS_REVIEW,
                confidence__gte=threshold,
            ).values_list("id", "product_id")
        )

        self.stdout.write(
            f"{len(candidates)} classification(s) at or above confidence "
            f"{threshold:g} in needs_review."
        )

        if dry_run or not candidates:
            return

        classification_ids = [cid for cid, _pid in candidates]
        product_ids = [pid for _cid, pid in candidates]

        with transaction.atomic():
            approved = Classification.objects.filter(
                id__in=classification_ids,
                status=Classification.Status.NEEDS_REVIEW,
            ).update(status=Classification.Status.APPROVED, updated_at=tz.now())

            # Only flip products still waiting on review; never touch
            # failed/processing/done rows.
            moved = Product.objects.filter(
                id__in=product_ids, status=Product.Status.NEEDS_REVIEW
            ).update(status=Product.Status.DONE, updated_at=tz.now())

        logger.info(
            "Auto-approved %d classifications (%d products moved to done)",
            approved,
            moved,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Approved {approved} classification(s); "
                f"{moved} product(s) moved to done."
            )
        )
