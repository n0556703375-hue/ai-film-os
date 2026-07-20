import unittest

from app.services.identity_vision import evaluate_shot_identity


class FakeAdapter:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def compare_identity(self, *, reference_url, candidate_url):
        self.calls.append((reference_url, candidate_url))
        return self.results.pop(0)


class IdentityVisionTests(unittest.TestCase):
    def test_passes_when_all_locked_character_masters_pass(self):
        shot = {
            "assets": [
                {
                    "id": 1,
                    "asset_type": "דמות",
                    "name": "ליאורה",
                    "lock_status": "locked",
                    "reference_images": ["https://example.com/liora-master.jpg"],
                },
                {
                    "id": 2,
                    "asset_type": "דמות",
                    "name": "מיכל",
                    "lock_status": "locked",
                    "reference_images": ["https://example.com/michal-master.jpg"],
                },
            ]
        }
        adapter = FakeAdapter([
            {"identity_similarity": 0.94, "provider": "vision", "model": "test"},
            {"identity_similarity": 0.88, "provider": "vision", "model": "test"},
        ])

        result = evaluate_shot_identity(
            shot=shot,
            candidate_url="https://example.com/shot.jpg",
            adapter=adapter,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["identity_similarity"], 0.88)
        self.assertEqual(len(result["evidence"]["comparisons"]), 2)
        self.assertEqual(len(adapter.calls), 2)

    def test_blocks_when_any_character_comparison_fails(self):
        shot = {
            "assets": [{
                "id": 1,
                "asset_type": "דמות",
                "name": "ליאורה",
                "lock_status": "locked",
                "reference_images": ["https://example.com/master.jpg"],
            }]
        }
        adapter = FakeAdapter([{
            "identity_similarity": 0.95,
            "flags": ["different_person"],
            "evidence": {"face_count": 1},
        }])

        result = evaluate_shot_identity(
            shot=shot,
            candidate_url="https://example.com/shot.jpg",
            adapter=adapter,
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("different_person", result["blocking_flags"])
        self.assertTrue(result["reasons"][0].startswith("ליאורה:"))

    def test_ignores_unlocked_and_non_character_assets(self):
        shot = {
            "assets": [
                {
                    "id": 1,
                    "asset_type": "דמות",
                    "name": "טיוטה",
                    "lock_status": "review",
                    "reference_images": ["https://example.com/draft.jpg"],
                },
                {
                    "id": 2,
                    "asset_type": "לוקיישן",
                    "name": "מרום",
                    "lock_status": "locked",
                    "reference_images": ["https://example.com/location.jpg"],
                },
            ]
        }
        adapter = FakeAdapter([])

        result = evaluate_shot_identity(
            shot=shot,
            candidate_url="https://example.com/shot.jpg",
            adapter=adapter,
        )

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["passed"])
        self.assertEqual(adapter.calls, [])
        self.assertIn("No locked character master", result["reasons"][0])

    def test_requires_candidate_url(self):
        with self.assertRaises(ValueError):
            evaluate_shot_identity(shot={"assets": []}, candidate_url=" ", adapter=FakeAdapter([]))


if __name__ == "__main__":
    unittest.main()
