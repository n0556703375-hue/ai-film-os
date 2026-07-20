import json
import unittest

from app.repositories.approvals import _identity_drift_blocker


class IdentityDriftGateTests(unittest.TestCase):
    def test_legacy_media_without_assessment_remains_compatible(self):
        self.assertIsNone(_identity_drift_blocker({"magnific_task_id": "legacy"}))
        self.assertIsNone(_identity_drift_blocker(None))

    def test_explicit_pass_is_allowed(self):
        self.assertIsNone(
            _identity_drift_blocker(
                {"identity_drift": {"status": "completed", "passed": True}}
            )
        )

    def test_pending_assessment_is_blocked(self):
        blocker = _identity_drift_blocker(
            {"identity_drift": {"status": "pending"}}
        )
        self.assertIn("טרם הושלמה", blocker)

    def test_failed_assessment_uses_reasons(self):
        blocker = _identity_drift_blocker(
            {
                "identity_drift": {
                    "status": "blocked",
                    "passed": False,
                    "reasons": ["מבנה הפנים אינו תואם", "צבע השיער השתנה"],
                }
            }
        )
        self.assertIn("מבנה הפנים", blocker)
        self.assertIn("צבע השיער", blocker)

    def test_json_metadata_is_supported(self):
        metadata = json.dumps(
            {"identity_drift": {"status": "running"}}, ensure_ascii=False
        )
        self.assertIsNotNone(_identity_drift_blocker(metadata))

    def test_incomplete_assessment_fails_closed(self):
        self.assertIsNotNone(_identity_drift_blocker({"identity_drift": {}}))
        self.assertIsNotNone(
            _identity_drift_blocker(
                {"identity_drift": {"status": "completed", "passed": None}}
            )
        )


if __name__ == "__main__":
    unittest.main()
