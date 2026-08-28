import logging

from django.db.models import Count, Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from classification.models import Classification
from classification.serializers import ClassificationSerializer
from classification.services.review_service import (
    ReviewError,
    approve_classification,
    correct_classification,
)
from products.models import Product
from taxonomy.models import Category

logger = logging.getLogger(__name__)


class ClassificationJobStatusView(APIView):
    def get(self, request):
        from products.models import ProductImport

        latest_import = ProductImport.objects.order_by("-created_at").first()

        # Scope counts to the latest import when available
        if latest_import:
            base_qs = Product.objects.filter(product_import=latest_import)
        else:
            base_qs = Product.objects.all()

        counts = base_qs.aggregate(
            pending=Count("id", filter=Q(status="pending")),
            processing=Count("id", filter=Q(status="processing")),
            done=Count("id", filter=Q(status="done")),
            needs_review=Count("id", filter=Q(status="needs_review")),
            failed=Count("id", filter=Q(status="failed")),
        )
        total = base_qs.count()

        import_total_rows = latest_import.total_rows if latest_import else 0
        import_imported_rows = latest_import.imported_rows if latest_import else 0
        import_status = latest_import.status if latest_import else None

        return Response(
            {
                "total": total,
                "pending": counts["pending"],
                "processing": counts["processing"],
                "done": counts["done"],
                "needs_review": counts["needs_review"],
                "failed": counts["failed"],
                # Import-level progress (from ProductImport)
                "import_total_rows": import_total_rows,
                "import_imported_rows": import_imported_rows,
                "import_status": import_status,
            },
            status=status.HTTP_200_OK,
        )


class ReviewListView(APIView):
    def _collect_alt_cat_ids(self, classifications):
        cat_ids = set()
        for cls in classifications:
            for item in cls.alternatives or []:
                cid = (
                    item.get("category_id")
                    if isinstance(item, dict)
                    else getattr(item, "category_id", None)
                )
                if cid is not None:
                    cat_ids.add(cid)
        return cat_ids

    def get(self, request):
        qs = Classification.objects.select_related(
            "product", "category", "reviewed_by"
        ).prefetch_related(
            "attributes__attribute", "attributes__value", "product__images"
        )

        qs = qs.filter(status=Classification.Status.NEEDS_REVIEW)

        min_confidence = request.query_params.get("min_confidence")
        max_confidence = request.query_params.get("max_confidence")
        if min_confidence is not None:
            qs = qs.filter(confidence__gte=float(min_confidence))
        if max_confidence is not None:
            qs = qs.filter(confidence__lte=float(max_confidence))

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(product__title__icontains=search)

        qs = qs.order_by("-created_at")

        page = self.paginate_queryset(qs)
        if page is not None:
            cat_ids = self._collect_alt_cat_ids(page)
            alt_cache = (
                {c.id: c for c in Category.objects.filter(id__in=cat_ids)}
                if cat_ids
                else {}
            )
            ctx = {"request": request, "category_cache": alt_cache}
            serializer = ClassificationSerializer(page, many=True, context=ctx)
            return self.get_paginated_response(serializer.data)

        serializer = ClassificationSerializer(
            qs, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @property
    def paginator(self):
        if not hasattr(self, "_paginator"):
            from rest_framework.pagination import PageNumberPagination

            self._paginator = PageNumberPagination()
            self._paginator.page_size = 25
        return self._paginator

    def paginate_queryset(self, queryset):
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)


class ReviewDetailView(APIView):
    def get(self, request, pk):
        try:
            classification = (
                Classification.objects.select_related(
                    "product", "category", "reviewed_by"
                )
                .prefetch_related(
                    "attributes__attribute", "attributes__value", "product__images"
                )
                .get(pk=pk)
            )
        except Classification.DoesNotExist:
            return Response(
                {"error": "Classification not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ClassificationSerializer(
            classification, context={"request": request}
        )
        return Response(serializer.data)


class ReviewApproveView(APIView):
    def post(self, request, pk):
        try:
            classification = Classification.objects.select_related(
                "product", "category"
            ).get(pk=pk)
        except Classification.DoesNotExist:
            return Response(
                {"error": "Classification not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        reviewer = request.user if request.user.is_authenticated else None

        try:
            result = approve_classification(classification, reviewer)
        except ReviewError as exc:
            logger.warning("Approve failed for classification %d: %s", pk, exc)
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)

        serializer = ClassificationSerializer(result, context={"request": request})
        return Response(serializer.data)


class ClassifiedProductsView(APIView):
    PAGE_SIZE = 20

    def _available_category_tree(self, queryset):
        """Hierarchical categories derived from the products in `queryset`.

        Only categories that actually appear on the products are returned
        (with product counts), grouped beneath their root category. The
        queryset passed in must NOT have the category filter applied, so
        the options stay stable while browsing a selection.
        """
        counts = (
            queryset.exclude(category__isnull=True)
            .values("category_id")
            .annotate(total=Count("id"))
        )
        count_by_id = {row["category_id"]: row["total"] for row in counts}
        if not count_by_id:
            return []

        categories = list(
            Category.objects.filter(id__in=count_by_id).select_related("parent")
        )
        parent_ids = {c.parent_id for c in categories if c.parent_id}
        parents = (
            {p.id: p for p in Category.objects.filter(id__in=parent_ids)}
            if parent_ids
            else {}
        )

        roots = {}
        for cat in sorted(categories, key=lambda c: c.full_path):
            node = {
                "id": cat.id,
                "name": cat.name,
                "count": count_by_id[cat.id],
                "children": [],
            }
            if cat.parent_id:
                parent = parents[cat.parent_id]
                entry = roots.setdefault(
                    parent.id,
                    {
                        "id": parent.id,
                        "name": parent.name,
                        "count": 0,
                        "children": [],
                    },
                )
                entry["children"].append(node)
                entry["count"] += node["count"]
            else:
                entry = roots.setdefault(
                    cat.id,
                    {"id": cat.id, "name": cat.name, "count": 0, "children": []},
                )
                entry["count"] += node["count"]

        tree = sorted(roots.values(), key=lambda r: r["name"].lower())
        for entry in tree:
            entry["children"].sort(key=lambda c: c["name"].lower())
        return tree

    def get(self, request):
        qs = Classification.objects.select_related(
            "product", "category", "reviewed_by"
        ).prefetch_related(
            "attributes__attribute", "attributes__value", "product__images"
        )

        status_filter = request.query_params.get("status")
        if status_filter:
            valid_statuses = [s[0] for s in Classification.Status.choices]
            if status_filter in valid_statuses:
                qs = qs.filter(status=status_filter)

        source_filter = request.query_params.get("source")
        if source_filter:
            source_filter = source_filter.lower()
            if source_filter == "reviewed":
                qs = qs.filter(reviewed_by__isnull=False)
            elif source_filter in {"ai", "rule"}:
                qs = qs.filter(source__iexact=source_filter)

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(product__title__icontains=search)

        # Snapshot BEFORE applying the category filter: dropdown options are
        # generated from these products so they stay usable while filtered.
        base_qs = qs

        category_id = request.query_params.get("category")
        if category_id:
            try:
                category = Category.objects.get(pk=int(category_id))
            except (TypeError, ValueError, Category.DoesNotExist):
                return Response(
                    {"error": f"Unknown category: {category_id}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Match the category itself plus any descendant, so picking a
            # parent (e.g. Living Room) also returns its subcategories.
            qs = qs.filter(
                Q(category=category)
                | Q(category__full_path__istartswith=f"{category.full_path} > ")
            )

        qs = qs.order_by("-created_at")

        page = self.paginate_queryset(qs)
        if page is not None:
            cat_ids = self._collect_alt_cat_ids(page)
            alt_cache = (
                {c.id: c for c in Category.objects.filter(id__in=cat_ids)}
                if cat_ids
                else {}
            )
            ctx = {"request": request, "category_cache": alt_cache}
            serializer = ClassificationSerializer(page, many=True, context=ctx)
            response = self.get_paginated_response(serializer.data)
            response.data["available_categories"] = (
                self._available_category_tree(base_qs)
            )
            return response

        serializer = ClassificationSerializer(
            qs, many=True, context={"request": request}
        )
        return Response(serializer.data)

    def _collect_alt_cat_ids(self, classifications):
        cat_ids = set()
        for cls in classifications:
            for item in cls.alternatives or []:
                cid = (
                    item.get("category_id")
                    if isinstance(item, dict)
                    else getattr(item, "category_id", None)
                )
                if cid is not None:
                    cat_ids.add(cid)
        return cat_ids

    @property
    def paginator(self):
        if not hasattr(self, "_paginator"):
            from rest_framework.pagination import PageNumberPagination

            self._paginator = PageNumberPagination()
            self._paginator.page_size = self.PAGE_SIZE
        return self._paginator

    def paginate_queryset(self, queryset):
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)


class ReviewCorrectView(APIView):
    def post(self, request, pk):
        try:
            classification = Classification.objects.select_related(
                "product", "category"
            ).get(pk=pk)
        except Classification.DoesNotExist:
            return Response(
                {"error": "Classification not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        category_id = request.data.get("category_id")
        attributes = request.data.get("attributes")

        if classification.status != Classification.Status.NEEDS_REVIEW:
            msg = (
                "Cannot correct classification in status " f"'{classification.status}'"
            )
            return Response(
                {"error": msg},
                status=status.HTTP_409_CONFLICT,
            )

        reviewer = request.user if request.user.is_authenticated else None

        try:
            result = correct_classification(
                classification,
                reviewer,
                category_id=category_id,
                attributes=attributes,
            )
        except ReviewError as exc:
            logger.warning("Correct failed for classification %d: %s", pk, exc)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ClassificationSerializer(result, context={"request": request})
        return Response(serializer.data)
