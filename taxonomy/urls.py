from django.urls import path

from taxonomy.views import CategorySearchView

app_name = "taxonomy"

urlpatterns = [
    path(
        "api/taxonomy/categories/",
        CategorySearchView.as_view(),
        name="category-search",
    ),
]
