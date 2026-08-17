from django.contrib import admin

from .models import Attribute, AttributeValue, Category, CategoryAttribute


class AttributeValueInline(admin.TabularInline):
    model = AttributeValue
    extra = 0


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "full_path", "parent", "shopify_category_id")
    list_filter = ("parent",)
    search_fields = ("name", "full_path")


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)
    inlines = [AttributeValueInline]


@admin.register(AttributeValue)
class AttributeValueAdmin(admin.ModelAdmin):
    list_display = ("id", "attribute", "value")
    list_filter = ("attribute",)


@admin.register(CategoryAttribute)
class CategoryAttributeAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "attribute")
    list_filter = ("attribute",)
