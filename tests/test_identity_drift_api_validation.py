import unittest

from pydantic import ValidationError

from app.api.identity_assessments import (
    IdentityDriftAssessmentRequest,
    IdentityDriftEvaluationRequest,
)


class IdentityDriftApiValidationTests(unittest.TestCase):
    def test_evaluation_request_rejects_non_finite_similarity(self):
        for invalid_value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(identity_similarity=invalid_value):
                with self.assertRaises(ValidationError):
                    IdentityDriftEvaluationRequest(identity_similarity=invalid_value)

    def test_evaluation_request_rejects_non_finite_threshold(self):
        for invalid_value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(min_similarity=invalid_value):
                with self.assertRaises(ValidationError):
                    IdentityDriftEvaluationRequest(
                        identity_similarity=0.9,
                        min_similarity=invalid_value,
                    )

    def test_recorded_assessment_rejects_non_finite_score(self):
        for invalid_value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(score=invalid_value):
                with self.assertRaises(ValidationError):
                    IdentityDriftAssessmentRequest(
                        status="blocked",
                        passed=False,
                        score=invalid_value,
                    )


if __name__ == "__main__":
    unittest.main()
