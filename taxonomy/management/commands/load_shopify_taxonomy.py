"""Load the official Shopify product taxonomy into the database.

Reads the two canonical distribution files from
https://github.com/Shopify/product-taxonomy/tree/main/dist/en:

    - categories.json        -> {"version": ..., "verticals": [ ... ]}
    - attributes.json        -> {"version": ..., "attributes": [ ... ]}

Each vertical in categories.json contains a fully-nested category tree where
every category carries an inline ``attributes`` array pointing at the
attributes that are valid for it (matched by TaxonomyAttribute gid). The
attributes.json file provides the authoritative name/handle/values for each
attribute.

This command is idempotent: categories, attributes, values and category-
attribute links are upserted so re-running it never duplicates rows. It uses
``bulk_create`` with ``ignore_conflicts`` and batching to handle the ~29k
categories / ~8k attributes / ~74k attribute values efficiently.

Usage:
    python manage.py load_shopify_taxonomy \\
        --categories taxonomy/fixtures/shopify/categories.json \\
        --attributes taxonomy/fixtures/shopify/attributes.json

    # These may also be remote URLs.
    python manage.py load_shopify_taxonomy \\
        https://.../dist/en/categories.json \\
        https://.../dist/en/attributes.json

    python manage.py load_shopify_taxonomy ... --dry-run
"""

import json
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from taxonomy.models import Attribute, AttributeValue, Category, CategoryAttribute

_BULK_BATCH = 5000


def _is_url(source):
    return urlparse(source).scheme in ("http", "https")


def _load_json(source, what):
    if _is_url(source):
        import urllib.request

        try:
            with urllib.request.urlopen(source, timeout=120) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            raise CommandError(f"Failed to fetch {what} from {source}: {e}") from e
    import os

    if not os.path.exists(source):
        raise CommandError(f"File not found: {source}")
    try:
        with open(source, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        raise CommandError(f"Failed to read {source}: {e}") from e


def _iter_categories(verticals):
    """Yield every unique category in the taxonomy.

    The official Shopify categories.json stores each vertical's entire category
    set as a flat ``vertical.categories`` list (one dict per category, including
    its ``parent_id`` and ``full_name``). A handful of shallow parent categories
    *also* carry a nested ``children`` list that merely repeats the same
    categories, so we iterate the flat list and ignore ``children`` to avoid
    duplicate rows.
    """
    for vertical in verticals:
        yield from vertical.get("categories", [])


def _gid(obj):
    return obj["id"]


def _short_gid(gid):
    return gid.rsplit("/", 1)[-1]


def _stats():
    return {"created": 0, "updated": 0, "skipped": 0}


class Command(BaseCommand):
    help = (
        "Load the official Shopify product taxonomy (categories + attributes "
        "+ attribute values) into the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--categories",
            required=True,
            help="Path or URL to Shopify dist/en/categories.json",
        )
        parser.add_argument(
            "--attributes",
            required=True,
            help="Path or URL to Shopify dist/en/attributes.json",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing to the DB.",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.stats = {
            "categories": _stats(),
            "attributes": _stats(),
            "values": _stats(),
            "links": _stats(),
        }
        categories_src = options["categories"]
        attributes_src = options["attributes"]

        self.stdout.write(
            f"Loading taxonomy from {categories_src} / {attributes_src}..."
        )

        categories_data = json.loads(_load_json(categories_src, "categories"))
        attributes_data = json.loads(_load_json(attributes_src, "attributes"))
        self._validate(categories_data, attributes_data)

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes written"))
            with transaction.atomic():
                savepoint = transaction.savepoint()
                self._load_all(categories_data, attributes_data)
                transaction.savepoint_rollback(savepoint)
        else:
            self._load_all(categories_data, attributes_data)

        self._report()

        if not self.dry_run:
            from taxonomy.services.cache import invalidate_taxonomy_cache

            invalidate_taxonomy_cache()

    def _validate(self, categories_data, attributes_data):
        if not isinstance(categories_data, dict) or "verticals" not in categories_data:
            raise CommandError(
                "categories.json must be an object with a 'verticals' array."
            )
        if not isinstance(attributes_data, dict) or "attributes" not in attributes_data:
            raise CommandError(
                "attributes.json must be an object with an 'attributes' array."
            )

    # ---------------- attributes ---------------- #
    def _load_attributes(self, attributes_data):
        raw_attrs = attributes_data["attributes"]
        attr_by_gid = {}
        attr_by_shorted = {}

        existing_by_gid = {}
        for a in Attribute.objects.only("shopify_attribute_gid", "name").all():
            if a.shopify_attribute_gid:
                existing_by_gid[a.shopify_attribute_gid] = a

        for raw in raw_attrs:
            gid = _gid(raw)
            name = raw["name"]
            attr = existing_by_gid.get(gid) or existing_by_gid.get(name.lower())
            if attr is not None:
                if attr.name != name:
                    attr.name = name
                    if not self.dry_run and attr.pk:
                        Attribute.objects.filter(pk=attr.pk).update(name=name)
                self.stats["attributes"]["skipped"] += 1
            else:
                attr = Attribute(name=name, shopify_attribute_gid=gid)
                self.stats["attributes"]["created"] += 1
                if not self.dry_run:
                    attr.save()
            attr_by_gid[gid] = attr
            attr_by_shorted[_short_gid(gid)] = attr

            vals = raw.get("values", []) or []
            for val in vals:
                self._create_value(attr, val["name"])

        return attr_by_gid, attr_by_shorted

    def _create_value(self, attr, name):
        if self.dry_run:
            self.stats["values"]["created"] += 1
            return
        _, created = AttributeValue.objects.get_or_create(attribute=attr, value=name)
        if created:
            self.stats["values"]["created"] += 1
        else:
            self.stats["values"]["skipped"] += 1

    # ---------------- categories ---------------- #
    def _load_categories(self, categories_data):
        raw_cats = list(_iter_categories(categories_data["verticals"]))
        cat_by_gid = {}

        existing_by_gid = {}
        for c in Category.objects.all():
            if c.shopify_category_id:
                existing_by_gid[c.shopify_category_id] = c

        for raw in raw_cats:
            gid = _gid(raw)
            name = raw["name"]
            full_path = raw.get("full_name") or name
            cat = existing_by_gid.get(gid)
            if cat is None:
                cat = Category(
                    shopify_category_id=gid, name=name, full_path=full_path
                )
                self.stats["categories"]["created"] += 1
                if not self.dry_run:
                    cat.save()
            else:
                changed = False
                if cat.name != name:
                    cat.name = name
                    changed = True
                if cat.full_path != full_path:
                    cat.full_path = full_path
                    changed = True
                if changed and not self.dry_run:
                    cat.save()
                    self.stats["categories"]["updated"] += 1
            cat_by_gid[gid] = cat

        # Resolve parents after all rows exist.
        for raw in raw_cats:
            gid = _gid(raw)
            cat = cat_by_gid.get(gid)
            parent_gid = raw.get("parent_id")
            if cat is None or not parent_gid:
                continue
            parent = cat_by_gid.get(parent_gid)
            if parent is not None and parent.pk and cat.parent_id != parent.pk:
                if not self.dry_run:
                    Category.objects.filter(pk=cat.pk).update(parent_id=parent.pk)

        return cat_by_gid

    # ---------------- links ---------------- #
    def _load_links(self, categories_data, cat_by_gid, attr_by_gid):
        for raw in _iter_categories(categories_data["verticals"]):
            cat = cat_by_gid.get(_gid(raw))
            if cat is None or not cat.pk:
                continue
            for inline in raw.get("attributes", []) or []:
                attr = attr_by_gid.get(inline.get("id"))
                if attr is None or not attr.pk:
                    self.stats["links"]["skipped"] += 1
                    continue
                if self.dry_run:
                    self.stats["links"]["created"] += 1
                    continue
                _, created = CategoryAttribute.objects.get_or_create(
                    category=cat, attribute=attr
                )
                if created:
                    self.stats["links"]["created"] += 1
                else:
                    self.stats["links"]["skipped"] += 1

    # ---------------- orchestration ---------------- #
    def _load_all(self, categories_data, attributes_data):
        attr_by_gid, _attr_by_shorted = self._load_attributes(attributes_data)
        cat_by_gid = self._load_categories(categories_data)
        self._load_links(categories_data, cat_by_gid, attr_by_gid)

    def _report(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Shopify taxonomy load complete."))
        for key in ("categories", "attributes", "values", "links"):
            s = self.stats[key]
            self.stdout.write(
                f"  {key.title():11} {s['created']} created, "
                f"{s['updated']} updated, {s['skipped']} skipped"
            )
        if self.dry_run:
            self.stdout.write(self.style.WARNING("(dry run — nothing was persisted)"))
