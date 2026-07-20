import unittest

from app.repositories.approvals import _identity_drift_blocker


class IdentityDriftApprovalGateTests(unittest.TestCase):
    def test_blocks_failed_assessment_from_dict_metadata(self):
        blocker = _identity_drift_blocker({
            "identity_drift": {
                "status": "blocked",
                "passed": False,
                "reasons": ["Identity similarity is below threshold."],
            }
        })

        self.assertIn("below threshold", blocker)

    def test_blocks_failed_assessment_from_json_metadata(self):
        blocker = _identity_drift_blocker(
            '{"identity_drift":{"status":"blocked","passed":false,"reasons":[]}}'
        )

        self.assertEqual("בדיקת זהות הדמות נכשלה.", blocker)

    def test_allows_passed_or_missing_assessment(self):
        self.assertIsNone(_identity_drift_blocker({
            "identity_drift": {"status": "passed", "passed": True}
        }))
        self.assertIsNone(_identity_drift_blocker({"provider_job_id": "safe-example"}))
        self.assertIsNone(_identity_drift_blocker("not-json"))


if __name__ == "__main__":
    unittest.main()
