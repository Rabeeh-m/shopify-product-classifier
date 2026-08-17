import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("shopify_product_classifier")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "requeue-stuck-products": {
        "task": "products.tasks.requeue_stuck_products_task",
        "schedule": crontab(minute="*/15"),
    },
}
