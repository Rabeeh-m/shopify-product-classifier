from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from taxonomy.models import Category
from taxonomy.serializers import CategoryListSerializer


class CategorySearchView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        search = request.query_params.get("search", "")
        qs = Category.objects.all()
        if search:
            qs = qs.filter(full_path__icontains=search)
        qs = qs.order_by("full_path")[:20]
        serializer = CategoryListSerializer(qs, many=True)
        return Response(serializer.data)
