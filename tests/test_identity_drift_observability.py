import unittest

from app.services.identity_drift_observability import (
    summarize_completed_identity_drift,
)


class IdentityDriftObservabilityTests(unittest.TestCase):
    def test_returns_operator_safe_completion_audit_summary(self):
        assessment = {
            "status": "passed",
            "passed": True,
            "score": 0.97,
            "worker_id": "identity-worker-1",
            "attempt": 2,
            "claimed_at": "2026-07-26T01:00:00+00:00",
            "completed_at": "2026-07-26T01:01:00+00:00",
            "provider": "openai",
            "model": "vision-model",
            "reasons": [],
            "evidence": {"raw_provider_payload": "must-not-leak"},
        }

        summary = summarize_completed_identity_drift(assessment)

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["worker_id"], "identity-worker-1")
        self.assertEqual(summary["attempt"], 2)
        self.assertEqual(summary["completed_at"], "2026-07-26T01:01:00+00:00")
        self.assertNotIn("evidence", summary)
        self.assertNotIn("raw_provider_payload", summary)

    def test_ignores_pending_and_running_assessments(self):
        for status in ("pending", "running", None):
            with self.subTest(status=status):
                self.assertIsNone(
                    summarize_completed_identity_drift({"status": status})
                )

    def test_does_not_mutate_stored_assessment_or_reasons(self):
        reasons = ["identity similarity below threshold"]
        assessment = {
            "status": "blocked",
            "passed": False,
            "reasons": reasons,
        }

        summary = summarize_completed_identity_drift(assessment)
        summary["reasons"].append("operator note")

        self.assertEqual(reasons, ["identity similarity below threshold"])
        self.assertEqual(
            assessment["reasons"],
            ["identity similarity below threshold"],
        )

    def test_rejects_non_mapping_input(self):
        self.assertIsNone(summarize_completed_identity_drift(None))


if __name__ == "__main__":
    unittest.main()
