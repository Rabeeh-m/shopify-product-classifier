from django.core.management.base import BaseCommand

from classification.tasks import process_products
from products.models import Product


class Command(BaseCommand):
    help = "Classify pending products (vendor rules first, AI fallback)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--import-id",
            type=int,
            default=None,
            help="Only classify products from this import.",
        )

    def handle(self, *args, **options):
        import_id = options["import_id"]
        qs = Product.objects.filter(status__in=["pending", "processing"])
        if import_id is not None:
            qs = qs.filter(product_import_id=import_id)
        count = qs.count()

        if count == 0:
            self.stdout.write("No pending products to classify.")
            return

        self.stdout.write(f"Classifying {count} products...")
        result = process_products(import_id=import_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {result['processed']} processed, "
                f"{result['failed']} failed."
            )
        )
