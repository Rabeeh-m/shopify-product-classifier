from rest_framework import serializers

from classification.models import Classification, ClassificationAttribute
from taxonomy.models import Category


class ClassificationAttributeSerializer(serializers.ModelSerializer):
    attribute_name = serializers.CharField(source="attribute.name", read_only=True)
    value_display = serializers.SerializerMethodField()

    class Meta:
        model = ClassificationAttribute
        fields = ["attribute_name", "value_display", "free_text_value"]

    def get_value_display(self, obj):
        return str(obj.value) if obj.value else obj.free_text_value


class ProductMinimalSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    image_urls = serializers.SerializerMethodField()

    def get_image_urls(self, obj):
        request = self.context.get("request")
        images = obj.images.all()
        urls = [img.url for img in images]
        if request:
            return [request.build_absolute_uri(url) for url in urls]
        return urls


class CategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    full_path = serializers.CharField()


class AlternativeSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    category = serializers.SerializerMethodField()
    confidence = serializers.FloatField()

    def get_category(self, obj):
        cat_id = obj.get("category_id") if isinstance(obj, dict) else obj.category_id
        cache = self.context.get("category_cache", {})
        if cat_id in cache:
            cat = cache[cat_id]
            return CategorySerializer(cat).data
        try:
            cat = Category.objects.get(id=cat_id)
            cache[cat_id] = cat
            self.context["category_cache"] = cache
            return CategorySerializer(cat).data
        except Category.DoesNotExist:
            return None


class ClassificationSerializer(serializers.ModelSerializer):
    product = ProductMinimalSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    alternatives = serializers.SerializerMethodField()
    attributes = ClassificationAttributeSerializer(many=True, read_only=True)
    reviewed_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Classification
        fields = [
            "id",
            "product",
            "category",
            "alternatives",
            "attributes",
            "confidence",
            "status",
            "reviewed_by",
            "reviewed_at",
            "correction_notes",
            "created_at",
            "updated_at",
        ]

    def get_alternatives(self, obj):
        raw = obj.alternatives or []
        if not raw:
            return []

        cat_ids = {
            item.get("category_id") if isinstance(item, dict) else item.category_id
            for item in raw
            if item
        }
        if not cat_ids:
            return []

        # Use the context-provided cache (shared across all serializer instances
        # in the same request). Only query DB for IDs not already cached.
        ctx_cache = self.context.get("category_cache")
        if ctx_cache is None:
            ctx_cache = {}
            self.context["category_cache"] = ctx_cache

        missing = cat_ids - ctx_cache.keys()
        if missing:
            ctx_cache.update({c.id: c for c in Category.objects.filter(id__in=missing)})

        return AlternativeSerializer(raw, many=True, context=self.context).data
