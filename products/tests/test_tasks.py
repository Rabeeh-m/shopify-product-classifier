from unittest.mock import patch

from django.test import TestCase

from products.tasks import requeue_stuck_products_task


class RequeueStuckProductsTaskTest(TestCase):
    @patch("products.tasks.call_command")
    def test_task_calls_management_command(self, mock_call):
        requeue_stuck_products_task()
        mock_call.assert_called_once_with("requeue_stuck_products")
