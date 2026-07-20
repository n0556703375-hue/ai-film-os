import unittest

from app.services.identity_drift import assess_identity_drift


class IdentityDriftTests(unittest.TestCase):
    def test_passes_when_similarity_is_high_and_no_critical_flags_exist(self):
        result = assess_identity_drift(
            identity_similarity=0.93,
            flags=["lighting_changed", "expression_changed"],
            evidence={"reference_id": 10, "candidate_id": 22},
        )

        self.assertTrue(result["passed"])
        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["blocking_flags"])
        self.assertEqual(10, result["evidence"]["reference_id"])

    def test_blocks_when_similarity_is_below_threshold(self):
        result = assess_identity_drift(identity_similarity=0.71)

        self.assertFalse(result["passed"])
        self.assertEqual("blocked", result["status"])
        self.assertIn("below the required", result["reasons"][0])

    def test_critical_flag_blocks_even_with_high_similarity(self):
        result = assess_identity_drift(
            identity_similarity=0.98,
            flags=["different_person", "lighting_changed", "different_person"],
        )

        self.assertFalse(result["passed"])
        self.assertEqual(["different_person"], result["blocking_flags"])
        self.assertEqual(["different_person", "lighting_changed"], result["flags"])

    def test_custom_threshold_is_supported(self):
        result = assess_identity_drift(identity_similarity=0.79, min_similarity=0.75)

        self.assertTrue(result["passed"])
        self.assertEqual(0.75, result["min_similarity"])

    def test_rejects_invalid_scores_and_thresholds(self):
        with self.assertRaises(ValueError):
            assess_identity_drift(identity_similarity=1.01)
        with self.assertRaises(ValueError):
            assess_identity_drift(identity_similarity=0.9, min_similarity=0)


if __name__ == "__main__":
    unittest.main()
