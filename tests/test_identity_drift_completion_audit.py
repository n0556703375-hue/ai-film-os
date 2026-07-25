import unittest
from datetime import datetime, timezone

from app.services.identity_drift_worker import (
    build_completed_identity_drift_assessment,
)


class IdentityDriftCompletionAuditTests(unittest.TestCase):
    def test_preserves_claim_metadata_and_adds_completion_timestamp(self):
        claimed_at = "2026-07-25T17:00:00+00:00"
        completed_at = datetime(2026, 7, 25, 17, 5, tzinfo=timezone.utc)
        running = {
            "status": "running",
            "worker_id": "identity-worker-1",
            "claimed_at": claimed_at,
            "attempt": 3,
        }

        completed = build_completed_identity_drift_assessment(
            running,
            {"status": "passed", "passed": True, "score": 0.96},
            " identity-worker-1 ",
            completed_at=completed_at,
        )

        self.assertEqual(completed["worker_id"], "identity-worker-1")
        self.assertEqual(completed["attempt"], 3)
        self.assertEqual(completed["claimed_at"], claimed_at)
        self.assertEqual(completed["completed_at"], "2026-07-25T17:05:00+00:00")
        self.assertEqual(completed["status"], "passed")

    def test_rejects_naive_completion_timestamp(self):
        running = {
            "status": "running",
            "worker_id": "identity-worker-1",
            "attempt": 1,
        }

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            build_completed_identity_drift_assessment(
                running,
                {"status": "passed", "passed": True, "score": 0.96},
                "identity-worker-1",
                completed_at=datetime(2026, 7, 25, 17, 5),
            )

    def test_does_not_mutate_claim_or_result(self):
        running = {
            "status": "running",
            "worker_id": "identity-worker-1",
            "attempt": 1,
        }
        result = {"status": "blocked", "passed": False, "reasons": ["drift"]}

        build_completed_identity_drift_assessment(
            running,
            result,
            "identity-worker-1",
            completed_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        )

        self.assertEqual(running["status"], "running")
        self.assertNotIn("completed_at", running)
        self.assertNotIn("worker_id", result)
        self.assertNotIn("completed_at", result)


if __name__ == "__main__":
    unittest.main()
