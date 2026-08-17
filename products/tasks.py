import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task
def requeue_stuck_products_task():
    """Celery task wrapper for the requeue_stuck_products management command.

    This allows the command to be scheduled via Celery beat without
    requiring shell access.
    """
    logger.info("Running requeue_stuck_products...")
    call_command("requeue_stuck_products")
