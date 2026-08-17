from rest_framework import serializers

from taxonomy.models import Category


class CategoryListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "full_path"]
