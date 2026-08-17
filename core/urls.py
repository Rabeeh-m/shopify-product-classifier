from django.urls import path

from core.views import HealthCheckView

app_name = "core"

urlpatterns = [
    path("api/health/", HealthCheckView.as_view(), name="health-check"),
]
