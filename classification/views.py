from django.db.models import Count, Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from products.models import Product


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
