from django.urls import path

from classification.views import (
    ClassificationJobStatusView,
    ClassifiedProductDetailView,
    ClassifiedProductsView,
    ReviewApproveView,
    ReviewCorrectView,
    ReviewDetailView,
    ReviewListView,
)

app_name = "classification"

urlpatterns = [
    path(
        "api/classification/jobs/status/",
        ClassificationJobStatusView.as_view(),
        name="classification-job-status",
    ),
    path(
        "api/classification/products/",
        ClassifiedProductsView.as_view(),
        name="classified-products",
    ),
    path(
        "api/classification/products/<int:pk>/",
        ClassifiedProductDetailView.as_view(),
        name="classified-product-detail",
    ),
    path(
        "api/classification/review/",
        ReviewListView.as_view(),
        name="review-list",
    ),
    path(
        "api/classification/review/<int:pk>/",
        ReviewDetailView.as_view(),
        name="review-detail",
    ),
    path(
        "api/classification/review/<int:pk>/approve/",
        ReviewApproveView.as_view(),
        name="review-approve",
    ),
    path(
        "api/classification/review/<int:pk>/correct/",
        ReviewCorrectView.as_view(),
        name="review-correct",
    ),
]
