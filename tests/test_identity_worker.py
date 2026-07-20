import unittest
from unittest.mock import Mock, patch

from app.services.identity_worker import process_identity_assessment


class IdentityWorkerTests(unittest.TestCase):
    @patch("app.services.identity_worker.record_identity_drift")
    @patch("app.services.identity_worker.evaluate_shot_identity")
    @patch("app.services.identity_worker.shot_repo.get_shot")
    @patch("app.services.identity_worker.claim_identity_drift")
    def test_claims_evaluates_and_persists_passed_verdict(
        self,
        claim,
        get_shot,
        evaluate,
        record,
    ):
        claim.return_value = {
            "shot_id": 7,
            "media_id": 11,
            "url": "https://example.com/candidate.jpg",
        }
        get_shot.return_value = {"id": 7, "assets": []}
        evaluate.return_value = {
            "status": "passed",
            "passed": True,
            "identity_similarity": 0.94,
            "reasons": [],
            "provider": "vision-provider",
            "model": "identity-v1",
        }
        record.return_value = {
            "media": {"metadata": {"identity_drift": {"status": "passed", "passed": True}}}
        }

        result = process_identity_assessment(
            shot_id=7,
            media_id=11,
            worker_id="worker-1",
            adapter=Mock(),
        )

        self.assertEqual(result["identity_drift"]["status"], "passed")
        claim.assert_called_once()
        get_shot.assert_called_once_with(7)
        evaluate.assert_called_once()
        request = record.call_args.args[2]
        self.assertEqual(request.status, "passed")
        self.assertTrue(request.passed)
        self.assertEqual(request.score, 0.94)

    @patch("app.services.identity_worker.record_identity_drift")
    @patch("app.services.identity_worker.evaluate_shot_identity")
    @patch("app.services.identity_worker.shot_repo.get_shot")
    @patch("app.services.identity_worker.claim_identity_drift")
    def test_records_error_after_claim_when_adapter_fails(
        self,
        claim,
        get_shot,
        evaluate,
        record,
    ):
        claim.return_value = {
            "shot_id": 7,
            "media_id": 11,
            "url": "https://example.com/candidate.jpg",
        }
        get_shot.return_value = {"id": 7, "assets": []}
        evaluate.side_effect = RuntimeError("provider unavailable")
        record.return_value = {
            "media": {"metadata": {"identity_drift": {"status": "error", "passed": False}}}
        }

        result = process_identity_assessment(
            shot_id=7,
            media_id=11,
            worker_id="worker-1",
            adapter=Mock(),
        )

        self.assertEqual(result["identity_drift"]["status"], "error")
        request = record.call_args.args[2]
        self.assertEqual(request.status, "error")
        self.assertFalse(request.passed)
        self.assertIn("RuntimeError", request.reasons[0])

    @patch("app.services.identity_worker.claim_identity_drift")
    def test_does_not_evaluate_when_claim_fails(self, claim):
        claim.side_effect = RuntimeError("already claimed")

        with self.assertRaises(RuntimeError):
            process_identity_assessment(
                shot_id=7,
                media_id=11,
                worker_id="worker-2",
                adapter=Mock(),
            )


if __name__ == "__main__":
    unittest.main()
