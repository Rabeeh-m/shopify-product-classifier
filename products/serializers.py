from rest_framework import serializers

from products.models import ProductImport


class ProductImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImport
        fields = [
            "id",
            "file",
            "status",
            "total_rows",
            "imported_rows",
            "failed_rows",
            "error_log",
            "created_at",
            "completed_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "total_rows",
            "imported_rows",
            "failed_rows",
            "error_log",
            "created_at",
            "completed_at",
        ]
