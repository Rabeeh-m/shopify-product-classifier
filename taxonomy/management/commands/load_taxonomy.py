import json
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from taxonomy.models import Attribute, AttributeValue, Category, CategoryAttribute


def _is_url(source):
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https")


def _load_source(source):
    if _is_url(source):
        import urllib.request

        try:
            with urllib.request.urlopen(source, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise CommandError(f"Failed to fetch {source}: {e}")
    else:
        try:
            with open(source, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise CommandError(f"File not found: {source}")
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON in {source}: {e}")


def _validate_data(data, source):
    errors = []
    if not isinstance(data, dict):
        raise CommandError(
            f"Source {source} must be a JSON object with 'categories' and "
            "'attributes' keys"
        )
    for key in ("categories", "attributes"):
        if key not in data:
            errors.append(f"Missing required key '{key}'")
    if errors:
        raise CommandError(f"Invalid structure in {source}: {'; '.join(errors)}")
    if not isinstance(data["categories"], list):
        raise CommandError("'categories' must be a list")
    if not isinstance(data["attributes"], list):
        raise CommandError("'attributes' must be a list")
    for i, cat in enumerate(data["categories"]):
        if "id" not in cat:
            errors.append(f"categories[{i}] missing 'id'")
        if "name" not in cat:
            errors.append(f"categories[{i}] missing 'name'")
    for i, attr in enumerate(data["attributes"]):
        if "id" not in attr:
            errors.append(f"attributes[{i}] missing 'id'")
        if "name" not in attr:
            errors.append(f"attributes[{i}] missing 'name'")
        if "values" not in attr:
            errors.append(f"attributes[{i}] missing 'values'")
    if errors:
        raise CommandError(f"Validation errors in {source}: {'; '.join(errors)}")


def _compute_full_path(cat, cat_map, memo):
    if cat["id"] in memo:
        return memo[cat["id"]]
    parent_id = cat.get("parent")
    if parent_id and parent_id in cat_map:
        parent_path = _compute_full_path(cat_map[parent_id], cat_map, memo)
        full_path = f"{parent_path} > {cat['name']}"
    else:
        full_path = cat["name"]
    memo[cat["id"]] = full_path
    return full_path


def _load_categories(data, dry_run):
    raw_cats = data["categories"]
    cat_map = {r["id"]: r for r in raw_cats}
    memo = {}
    for raw in raw_cats:
        _compute_full_path(raw, cat_map, memo)

    stats = {"created": 0, "updated": 0, "skipped": 0}
    cat_objects = {}

    for raw in raw_cats:
        cat_id = raw["id"]
        full_path = memo[cat_id]
        shopify_id = raw.get("shopify_category_id", cat_id)
        name = raw["name"]

        existing = Category.objects.filter(shopify_category_id=shopify_id).first()
        if existing:
            changed = False
            if existing.name != name:
                existing.name = name
                changed = True
            if existing.full_path != full_path:
                existing.full_path = full_path
                changed = True
            if changed and not dry_run:
                existing.save(update_fields=["name", "full_path"])
            if changed:
                stats["updated"] += 1
            cat_objects[cat_id] = existing
        else:
            stats["created"] += 1
            if not dry_run:
                cat_obj = Category.objects.create(
                    shopify_category_id=shopify_id, name=name, full_path=full_path
                )
                cat_objects[cat_id] = cat_obj
            else:
                cat_objects[cat_id] = None

    for raw in raw_cats:
        parent_id = raw.get("parent")
        if not parent_id or parent_id not in cat_objects:
            continue
        cat_obj = cat_objects.get(raw["id"])
        parent_obj = cat_objects.get(parent_id)
        if cat_obj is None or parent_obj is None:
            continue
        if cat_obj.parent_id != parent_obj.pk:
            if not dry_run:
                cat_obj.parent = parent_obj
                cat_obj.save(update_fields=["parent"])

    return stats, cat_objects


def _load_attributes(data, dry_run):
    stats = {"created": 0, "updated": 0, "skipped": 0}
    value_stats = {"created": 0, "updated": 0, "skipped": 0}
    attr_objects = {}

    for raw in data["attributes"]:
        attr_name = raw["name"]
        handle = raw.get("handle", attr_name.lower().replace(" ", "_"))

        existing = Attribute.objects.filter(name=attr_name).first()
        if existing:
            stats["updated"] += 1
            attr_obj = existing
        else:
            stats["created"] += 1
            if not dry_run:
                attr_obj = Attribute.objects.create(name=attr_name)
            else:
                attr_obj = None

        attr_objects[attr_name] = attr_obj
        attr_objects[handle] = attr_obj

        if attr_obj is None:
            value_stats["skipped"] += len(raw["values"])
            continue
        for val_name in raw["values"]:
            if not val_name or not val_name.strip():
                continue
            exists = AttributeValue.objects.filter(
                attribute=attr_obj, value=val_name
            ).exists()
            if exists:
                value_stats["skipped"] += 1
            else:
                value_stats["created"] += 1
                if not dry_run:
                    AttributeValue.objects.create(attribute=attr_obj, value=val_name)

    return stats, attr_objects, value_stats


def _load_category_attributes(data, cat_objects, attr_objects, dry_run):
    stats = {"created": 0, "skipped": 0}

    for raw in data["categories"]:
        cat_obj = cat_objects.get(raw["id"])
        if cat_obj is None:
            continue
        for attr_key in raw.get("attributes", []):
            attr_obj = attr_objects.get(attr_key)
            if attr_obj is None:
                stats["skipped"] += 1
                continue
            exists = CategoryAttribute.objects.filter(
                category=cat_obj, attribute=attr_obj
            ).exists()
            if exists:
                stats["skipped"] += 1
            else:
                stats["created"] += 1
                if not dry_run:
                    CategoryAttribute.objects.create(
                        category=cat_obj, attribute=attr_obj
                    )

    return stats


class Command(BaseCommand):
    help = "Load Shopify product taxonomy from a JSON source file or URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="Path to a local JSON file or a URL to fetch taxonomy data from.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created/updated without writing to the DB.",
        )

    def handle(self, *args, **options):
        source = options["source"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Loading taxonomy from {source}...")

        data = _load_source(source)
        _validate_data(data, source)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN — no changes will be written")
            )
            with transaction.atomic():
                savepoint = transaction.savepoint()
                cat_stats, cat_objects = _load_categories(data, dry_run)
                attr_stats, attr_objects, value_stats = _load_attributes(data, dry_run)
                ca_stats = _load_category_attributes(
                    data, cat_objects, attr_objects, dry_run
                )
                transaction.savepoint_rollback(savepoint)
        else:
            cat_stats, cat_objects = _load_categories(data, dry_run)
            attr_stats, attr_objects, value_stats = _load_attributes(data, dry_run)
            ca_stats = _load_category_attributes(
                data, cat_objects, attr_objects, dry_run
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Taxonomy load complete."))
        self.stdout.write(
            f"  Categories:  {cat_stats['created']} created, "
            f"{cat_stats['updated']} updated, {cat_stats['skipped']} skipped"
        )
        self.stdout.write(
            f"  Attributes:  {attr_stats['created']} created, "
            f"{attr_stats['updated']} updated, {attr_stats['skipped']} skipped"
        )
        self.stdout.write(
            f"  Values:      {value_stats['created']} created, "
            f"{value_stats['updated']} updated, {value_stats['skipped']} skipped"
        )
        self.stdout.write(
            f"  Cat-Attr:    {ca_stats['created']} created, "
            f"{ca_stats['skipped']} skipped"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("(dry run — nothing was persisted)"))
        else:
            from taxonomy.services.cache import invalidate_taxonomy_cache

            invalidate_taxonomy_cache()
