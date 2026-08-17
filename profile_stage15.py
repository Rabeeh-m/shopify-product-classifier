#!/usr/bin/env python
"""Profile Stage 15 — N+1 query fixes, taxonomy caching, concurrency tuning."""

import json
import os
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.db import connection, reset_queries  # noqa: E402

from classification.models import Classification  # noqa: E402
from classification.services.candidate_finder import find_candidates  # noqa: E402
from classification.tasks import _run_pipeline  # noqa: E402
from products.models import Product  # noqa: E402
from taxonomy.models import Category  # noqa: E402

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "taxonomy", "fixtures", "sample_taxonomy.json"
)


def setup_fixtures():
    from django.core.management import call_command

    call_command("load_taxonomy", source=FIXTURE_PATH, verbosity=0)


def profile_review_list():
    """Profile the review list endpoint query count."""
    from rest_framework.test import APIRequestFactory, force_authenticate

    from classification.views import ReviewListView

    user = User.objects.first() or User.objects.create_user(
        username="prof", password="p"
    )

    # Create test data
    cat = Category.objects.first()
    pids = []
    for i in range(25):
        p = Product.objects.create(
            external_id=f"rl-{i}", title=f"Review List Product {i}"
        )
        pids.append(p.id)
        Classification.objects.create(
            product=p,
            category=cat,
            confidence=80.0,
            alternatives=[{"category_id": cat.id, "confidence": 60.0}],
            status=Classification.Status.NEEDS_REVIEW,
        )

    factory = APIRequestFactory()
    request = factory.get("/api/classification/review/")
    force_authenticate(request, user=user)

    view = ReviewListView.as_view()

    connection.force_debug_cursor = True
    reset_queries()
    start = time.perf_counter()
    view(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    query_count = len(connection.queries)
    connection.force_debug_cursor = False

    print(f"  Queries: {query_count}")
    print(f"  Time:    {elapsed_ms:.1f}ms")
    return query_count


def profile_candidate_finder():
    """Profile candidate_finder with taxonomy cache."""
    cache.clear()

    products = []
    for i in range(10):
        products.append(
            Product.objects.create(
                external_id=f"cf-{i}",
                title=f"Leather Sofa Furniture Chair {i}",
                description="High quality leather",
                product_type="furniture",
            )
        )

    connection.force_debug_cursor = True

    # Warm cache first
    reset_queries()
    find_candidates(products[0])
    warm_queries = len(connection.queries)
    print(f"  Cache warm (first call): {warm_queries} queries")

    # Subsequent calls should use cache
    reset_queries()
    start = time.perf_counter()
    for p in products:
        find_candidates(p)
    elapsed_ms = (time.perf_counter() - start) * 1000
    query_count = len(connection.queries)
    connection.force_debug_cursor = False

    print(f"  Queries (10 products, cached): {query_count}")
    print(f"  Time:    {elapsed_ms:.1f}ms")
    return query_count


def profile_pipeline_queries():
    """Profile pipeline query count with mocked AI."""
    cache.clear()
    cat = Category.objects.first()

    product = Product.objects.create(
        external_id="pipe-test",
        title="Leather Sofa",
        description="Fine leather sofa",
    )

    from unittest.mock import patch

    with patch("classification.services.classifier.call_ai") as mock_ai:
        mock_ai.return_value = json.dumps(
            {
                "chosen_category_id": cat.id,
                "confidence": 85.0,
                "alternatives": [],
                "attributes": [],
                "reasoning": "test",
            }
        )
        connection.force_debug_cursor = True
        reset_queries()
        start = time.perf_counter()
        _run_pipeline(product)
        elapsed_ms = (time.perf_counter() - start) * 1000
        query_count = len(connection.queries)
        connection.force_debug_cursor = False

    print(f"  Queries (1 product): {query_count}")
    print(f"  Time:    {elapsed_ms:.1f}ms")
    return query_count


if __name__ == "__main__":
    setup_fixtures()

    print("\n=== Review List Endpoint (25 classifications) ===")
    profile_review_list()

    print("\n=== Candidate Finder (10 products, after cache warm) ===")
    profile_candidate_finder()

    print("\n=== Classification Pipeline (1 product) ===")
    profile_pipeline_queries()
