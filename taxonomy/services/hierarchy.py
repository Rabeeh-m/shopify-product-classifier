"""In-memory category-tree helpers for hierarchical classification.

The full Shopify taxonomy (~14.6k categories) is far too large to send to the
AI model in a single prompt, so the classifier walks the tree level by level.
This module exposes a cached view of the category tree (roots + children of a
category) to make those lookups cheap and avoid N+1 queries.
"""

import logging

from django.conf import settings
from django.core.cache import cache

from taxonomy.models import Category

logger = logging.getLogger(__name__)

_CACHE_KEY = "taxonomy:category_tree"


def _get_ttl():
    return getattr(settings, "TAXONOMY_CACHE_TTL", 3600)


def _build_tree():
    cats = list(Category.objects.all())
    by_id = {c.id: c for c in cats}
    children = {}
    roots = []
    for c in cats:
        children.setdefault(c.parent_id, []).append(c)
        if c.parent_id is None:
            roots.append(c)
    for pid in children:
        children[pid].sort(key=lambda x: x.name.lower())
    roots.sort(key=lambda x: x.name.lower())
    tree = {"by_id": by_id, "children": children, "roots": roots}
    cache.set(_CACHE_KEY, tree, _get_ttl())
    logger.debug("Built category tree with %d categories", len(cats))
    return tree


def get_tree():
    """Return the cached tree dict {by_id, children, roots}."""
    tree = cache.get(_CACHE_KEY)
    if tree is None:
        tree = _build_tree()
    return tree


def invalidate_tree():
    cache.delete(_CACHE_KEY)


def get_root_categories():
    """Top-level categories (no parent)."""
    return get_tree()["roots"]


def get_children(category):
    """Direct children of a category (may be an id or a Category)."""
    pid = category.id if hasattr(category, "id") else category
    return get_tree()["children"].get(pid, [])
