import logging

from django.db.models import Count, Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
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


class ReviewWriteThrottle(UserRateThrottle):
    rate = "30/minute"


class ClassificationJobStatusView(APIView):
    def get(self, request):
        counts = Product.objects.aggregate(
            pending=Count("id", filter=Q(status="pending")),
            processing=Count("id", filter=Q(status="processing")),
            done=Count("id", filter=Q(status="done")),
            needs_review=Count("id", filter=Q(status="needs_review")),
            failed=Count("id", filter=Q(status="failed")),
        )
        total = Product.objects.count()
        return Response(
            {
                "total": total,
                "pending": counts["pending"],
                "processing": counts["processing"],
                "done": counts["done"],
                "needs_review": counts["needs_review"],
                "failed": counts["failed"],
            },
            status=status.HTTP_200_OK,
        )


class ReviewListView(APIView):
    def _collect_alt_cat_ids(self, classifications):
        """Gather all unique category_ids referenced in alternatives across a page."""
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
            # Bulk-load all alternative categories for the whole page in one query.
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
    throttle_classes = [ReviewWriteThrottle]

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


class ReviewCorrectView(APIView):
    throttle_classes = [ReviewWriteThrottle]

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
