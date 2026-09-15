import unittest

from mcp_autogui.public_response import reduce_public_response


class PublicResponseTests(unittest.TestCase):
    def test_task_state_is_the_authoritative_public_status(self):
        response = reduce_public_response(
            "run", task_state="needs-confirmation", object_ref="decision-1"
        )

        self.assertEqual(response["status"], "needs-confirmation")
        self.assertEqual(response["task_state"], "needs-confirmation")
        self.assertEqual(response["object_ref"], "decision-1")

    def test_error_reduces_to_failed_without_diagnostic_fields(self):
        response = reduce_public_response(
            "run", task_state="running", error={"code": "EXECUTOR_FAILED"}
        )

        self.assertEqual(response["status"], "failed")
        self.assertNotIn("object", response)
        self.assertNotIn("attribution_refs", response)

    def test_non_task_operation_is_completed(self):
        response = reduce_public_response("describe", task_state=None)

        self.assertEqual(response["status"], "completed")
