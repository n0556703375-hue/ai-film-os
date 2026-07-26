import unittest

from app.services.production_brain import evaluate_production_snapshot


class ProductionBrainTests(unittest.TestCase):
    def test_blocks_unlocked_character_and_dependent_shot(self):
        snapshot = {
            "project": {"id": 7, "name": "Film"},
            "assets": [{
                "id": 11,
                "asset_type": "דמות",
                "name": "ליאורה",
                "lock_status": "review",
                "master_reference_id": 101,
            }],
            "shots": [{
                "id": 21,
                "status": "פרומפט מוכן",
                "asset_ids": [11],
            }],
        }

        result = evaluate_production_snapshot(snapshot)

        self.assertEqual(result["project_status"], "blocked")
        self.assertEqual(
            [item["type"] for item in result["blockers"]],
            ["missing_character_lock", "shot_missing_locked_references"],
        )
        self.assertEqual(result["ready_actions"], [])
        self.assertTrue(result["read_only"])

    def test_recommends_image_generation_only_with_locked_references(self):
        snapshot = {
            "project": {"id": 7},
            "assets": [{
                "id": 11,
                "asset_type": "character",
                "name": "Lead",
                "lock_status": "locked",
                "master_reference_id": 101,
            }],
            "shots": [{
                "id": 21,
                "status": "prompt_ready",
                "asset_ids": [11],
            }],
        }

        result = evaluate_production_snapshot(snapshot)

        self.assertEqual(result["project_status"], "ready")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["ready_actions"], [{
            "type": "generate_shot_image",
            "shot_id": 21,
            "requires_confirmation": True,
        }])

    def test_blocked_shot_never_becomes_ready_action(self):
        result = evaluate_production_snapshot({
            "project": {"id": 1},
            "assets": [],
            "shots": [{"id": 3, "status": "blocked", "asset_ids": []}],
        })

        self.assertEqual(result["blockers"][0]["type"], "shot_blocked")
        self.assertEqual(result["ready_actions"], [])

    def test_does_not_mutate_snapshot(self):
        snapshot = {
            "project": {"id": 1},
            "assets": [],
            "shots": [{"id": 3, "status": "planned", "asset_ids": []}],
        }
        original = {
            "project": dict(snapshot["project"]),
            "assets": list(snapshot["assets"]),
            "shots": [dict(snapshot["shots"][0])],
        }

        evaluate_production_snapshot(snapshot)

        self.assertEqual(snapshot, original)


if __name__ == "__main__":
    unittest.main()
