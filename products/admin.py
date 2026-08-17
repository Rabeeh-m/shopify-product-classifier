from django.contrib import admin

from .models import Product, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "brand", "product_type", "status", "created_at")
    list_filter = ("status", "brand", "product_type")
    search_fields = ("title", "external_id")
    inlines = [ProductImageInline]


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "url", "is_valid", "created_at")
    list_filter = ("is_valid",)
