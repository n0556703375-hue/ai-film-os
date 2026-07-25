import unittest

from app.services.identity_drift_worker import (
    validate_identity_drift_worker_ownership,
)


class IdentityDriftWorkerOwnershipTests(unittest.TestCase):
    def test_accepts_the_worker_that_claimed_the_running_assessment(self):
        assessment = {"status": "running", "worker_id": "identity-worker-1"}

        worker_id = validate_identity_drift_worker_ownership(
            assessment,
            "  identity-worker-1  ",
        )

        self.assertEqual(worker_id, "identity-worker-1")

    def test_rejects_a_different_worker(self):
        assessment = {"status": "running", "worker_id": "identity-worker-1"}

        with self.assertRaisesRegex(ValueError, "another worker"):
            validate_identity_drift_worker_ownership(
                assessment,
                "identity-worker-2",
            )

    def test_rejects_assessment_that_is_not_running(self):
        assessment = {"status": "pending", "worker_id": "identity-worker-1"}

        with self.assertRaisesRegex(ValueError, "not currently running"):
            validate_identity_drift_worker_ownership(
                assessment,
                "identity-worker-1",
            )

    def test_rejects_missing_claimed_worker(self):
        assessment = {"status": "running"}

        with self.assertRaisesRegex(ValueError, "no valid claimed worker"):
            validate_identity_drift_worker_ownership(
                assessment,
                "identity-worker-1",
            )

    def test_rejects_blank_completing_worker(self):
        assessment = {"status": "running", "worker_id": "identity-worker-1"}

        with self.assertRaisesRegex(ValueError, "non-whitespace"):
            validate_identity_drift_worker_ownership(assessment, "   ")


if __name__ == "__main__":
    unittest.main()
