import unittest
from unittest.mock import patch

from app.api.identity_assessments import (
    IdentityDriftAssessmentRequest,
    IdentityDriftEvaluationRequest,
    evaluate_and_record_identity_drift,
    record_identity_drift,
)


class IdentityDriftCompletionOwnershipTests(unittest.TestCase):
    @patch("app.api.identity_assessments._store_identity_drift")
    def test_record_endpoint_passes_normalized_worker_separately(self, store):
        store.return_value = {"ok": True}
        request = IdentityDriftAssessmentRequest(
            worker_id="  identity-worker-1  ",
            status="passed",
            passed=True,
            score=0.97,
        )

        result = record_identity_drift(10, 20, request)

        self.assertEqual(result, {"ok": True})
        assessment = store.call_args.args[2]
        self.assertNotIn("worker_id", assessment)
        self.assertEqual(store.call_args.args[3], "identity-worker-1")

    @patch("app.api.identity_assessments._store_identity_drift")
    @patch("app.api.identity_assessments.assess_identity_drift")
    def test_evaluate_endpoint_passes_claiming_worker_to_store(self, assess, store):
        assess.return_value = {
            "status": "passed",
            "passed": True,
            "score": 0.95,
            "reasons": [],
        }
        store.return_value = {"ok": True}
        request = IdentityDriftEvaluationRequest(
            worker_id="identity-worker-1",
            identity_similarity=0.95,
        )

        result = evaluate_and_record_identity_drift(10, 20, request)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(store.call_args.args[3], "identity-worker-1")


if __name__ == "__main__":
    unittest.main()
