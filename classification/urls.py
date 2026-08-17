from django.urls import path

from classification.views import ClassificationJobStatusView

app_name = "classification"

urlpatterns = [
    path(
        "api/classification/jobs/status/",
        ClassificationJobStatusView.as_view(),
        name="classification-job-status",
    ),
]
