from django.urls import path

from products.views import ProductImportCreateView, ProductImportDetailView

app_name = "products"

urlpatterns = [
    path(
        "api/products/import/",
        ProductImportCreateView.as_view(),
        name="product-import-create",
    ),
    path(
        "api/products/import/<int:pk>/",
        ProductImportDetailView.as_view(),
        name="product-import-detail",
    ),
]
