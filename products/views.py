import logging
import os

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from products.models import Product, ProductImage, ProductImport
from products.serializers import ProductImportSerializer
from products.services.import_service import ParseError, validate_and_save_import

logger = logging.getLogger(__name__)


class ProductImportCreateView(APIView):
    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"error": "No file provided. Send a file as 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            import_obj = validate_and_save_import(upload, upload.name)
        except ParseError as exc:
            logger.warning("Upload rejected: %s", exc.errors)
            return Response(
                {"errors": exc.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Run import + classification on a background thread — this returns
        # immediately so the HTTP response comes back in < 1 s.
        from classification.tasks import start_import_background

        start_import_background(import_obj.id)

        # Pick up any progress made by the worker before serialization
        # (e.g. when running the pipeline synchronously in tests).
        import_obj.refresh_from_db()

        serializer = ProductImportSerializer(import_obj)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class LatestProductImportView(APIView):
    def get(self, request):
        """Return the most recent import so the UI can restore progress."""
        import_obj = ProductImport.objects.order_by("-id").first()
        if import_obj is None:
            return Response(
                {"error": "No imports yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ProductImportSerializer(import_obj)
        return Response(serializer.data)


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


class ClearAllProductsView(APIView):
    def delete(self, request):
        from classification.models import Classification, ClassificationAttribute

        product_ids = list(Product.objects.values_list("id", flat=True))

        ClassificationAttribute.objects.filter(
            classification__product_id__in=product_ids
        ).delete()

        Classification.objects.filter(product_id__in=product_ids).delete()

        ProductImage.objects.filter(product_id__in=product_ids).delete()

        import_files = ProductImport.objects.values_list("file", flat=True)
        import_files_list = list(import_files)

        ProductImport.objects.all().delete()
        Product.objects.all().delete()

        for f in import_files_list:
            try:
                file_path = os.path.join(settings.MEDIA_ROOT, f)
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as exc:
                logger.warning("Failed to remove import file %s: %s", f, exc)

        return Response(
            {"message": "All products, classifications, and imports cleared."},
            status=status.HTTP_200_OK,
        )
