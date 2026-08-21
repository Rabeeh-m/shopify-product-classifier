"""Taxonomy caching layer (local memory).

Loads the full category list once per cache TTL, avoiding repeated DB
hits during classification and in the frontend category picker.

Cache key: "taxonomy:all_categories"
TTL: configurable via TAXONOMY_CACHE_TTL (default 3600s = 1 hour)
"""

import logging

from django.conf import settings
from django.core.cache import cache

from taxonomy.models import Category

logger = logging.getLogger(__name__)

CACHE_KEY = "taxonomy:all_categories"


def get_ttl():
    """Return the taxonomy cache TTL in seconds from settings."""
    return getattr(settings, "TAXONOMY_CACHE_TTL", 3600)


def get_all_categories():
    """Return all Category objects, cached locally.

    Returns a list (not a queryset) to avoid lazy-evaluation surprises.
    """
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    categories = list(Category.objects.select_related("parent").order_by("full_path"))
    cache.set(CACHE_KEY, categories, get_ttl())
    logger.debug("Taxonomy cache miss — loaded %d categories from DB", len(categories))
    return categories


def invalidate_taxonomy_cache():
    """Explicitly remove the cached taxonomy.

    Called by load_taxonomy after a successful non-dry-run load.
    """
    cache.delete(CACHE_KEY)
    logger.info("Taxonomy cache invalidated")
