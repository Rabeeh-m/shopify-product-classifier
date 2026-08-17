from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from products.models import ProductImport
from products.serializers import ProductImportSerializer
from products.services.import_service import ParseError, import_products


class ProductImportCreateView(APIView):
    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"error": "No file provided. Send a file as 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            import_obj = import_products(upload, upload.name)
        except ParseError as exc:
            return Response(
                {"errors": exc.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from classification.tasks import process_all_pending

        process_all_pending.delay()

        serializer = ProductImportSerializer(import_obj)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ProductImportDetailView(APIView):
    def get(self, request, pk):
        try:
            import_obj = ProductImport.objects.get(pk=pk)
        except ProductImport.DoesNotExist:
            return Response(
                {"error": "Import not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ProductImportSerializer(import_obj)
        return Response(serializer.data)
