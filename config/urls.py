from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("", include("products.urls")),
    path("", include("classification.urls")),
    path("", include("taxonomy.urls")),
]
