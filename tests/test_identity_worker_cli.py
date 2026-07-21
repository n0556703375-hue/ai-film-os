import unittest
from unittest.mock import patch

from scripts.process_identity_assessments import (
    MAX_TASKS_LIMIT,
    resolve_worker_id,
    run,
)


class IdentityWorkerCliTests(unittest.TestCase):
    @patch("scripts.process_identity_assessments.process_next_identity_assessment")
    def test_processes_up_to_requested_bound(self, process_next):
        process_next.side_effect = [
            {"processed": True, "media_id": 1},
            {"processed": True, "media_id": 2},
            {"processed": False, "reason": "no_pending_identity_assessments"},
        ]

        summary = run(max_tasks=5, worker_id="worker-1")

        self.assertEqual(summary["processed_count"], 2)
        self.assertEqual([item["media_id"] for item in summary["results"]], [1, 2])
        self.assertEqual(process_next.call_count, 3)
        process_next.assert_called_with(worker_id="worker-1")

    @patch("scripts.process_identity_assessments.process_next_identity_assessment")
    def test_stops_at_hard_batch_limit(self, process_next):
        process_next.return_value = {"processed": True, "media_id": 1}

        summary = run(max_tasks=MAX_TASKS_LIMIT, worker_id="worker-1")

        self.assertEqual(summary["processed_count"], MAX_TASKS_LIMIT)
        self.assertEqual(process_next.call_count, MAX_TASKS_LIMIT)

    def test_rejects_invalid_batch_sizes(self):
        for invalid in (0, MAX_TASKS_LIMIT + 1):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "max_tasks must be between"):
                    run(max_tasks=invalid, worker_id="worker-1")

    def test_generates_non_secret_worker_id_when_not_configured(self):
        with patch("scripts.process_identity_assessments.socket.gethostname", return_value="host"), patch(
            "scripts.process_identity_assessments.os.getpid", return_value=42
        ):
            self.assertEqual(resolve_worker_id(""), "identity-worker-host-42")


if __name__ == "__main__":
    unittest.main()
