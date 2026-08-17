from django.contrib import admin

from .models import Classification, ClassificationAttribute


class ClassificationAttributeInline(admin.TabularInline):
    model = ClassificationAttribute
    extra = 0


@admin.register(Classification)
class ClassificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "category",
        "confidence",
        "status",
        "reviewed_by",
        "created_at",
    )
    list_filter = ("status", "category")
    search_fields = ("product__title",)
    inlines = [ClassificationAttributeInline]


@admin.register(ClassificationAttribute)
class ClassificationAttributeAdmin(admin.ModelAdmin):
    list_display = ("id", "classification", "attribute", "value", "free_text_value")
    list_filter = ("attribute",)
