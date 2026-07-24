import unittest
from pathlib import Path

from app.api.scenes import _import_progress_detail


ROOT = Path(__file__).resolve().parents[1]
SCENES_API = ROOT / "app" / "api" / "scenes.py"


class ScriptImportBackendProgressTests(unittest.TestCase):
    def test_progress_detail_preserves_persisted_counts_and_failed_scene(self):
        detail = _import_progress_detail(
            "temporary failure",
            {
                "completed_stages": ["screenplay_breakdown", "scene_persistence"],
                "failed_stage": "shot_map_generation",
                "scenes_created": 5,
                "shots_created": 12,
                "failed_scene_id": 44,
                "failed_scene_number": 3,
            },
            code="import_upstream_failure",
            retryable=True,
        )
        self.assertEqual(detail["completed_stages"], ["screenplay_breakdown", "scene_persistence"])
        self.assertEqual(detail["failed_stage"], "shot_map_generation")
        self.assertEqual(detail["scenes_created"], 5)
        self.assertEqual(detail["shots_created"], 12)
        self.assertEqual(detail["failed_scene_id"], 44)
        self.assertEqual(detail["failed_scene_number"], 3)
        self.assertTrue(detail["retryable"])

    def test_generic_upstream_error_does_not_expose_exception_text(self):
        source = SCENES_API.read_text(encoding="utf-8")
        self.assertIn('"ייבוא התסריט נעצר עקב תקלה זמנית."', source)
        self.assertNotIn('f"ייבוא התסריט נכשל: {exc}"', source)

    def test_shot_generation_remains_non_destructive(self):
        source = SCENES_API.read_text(encoding="utf-8")
        self.assertIn('repo.create_generated_shots(scene["id"], generated, False)', source)

    def test_success_response_contains_structured_progress(self):
        source = SCENES_API.read_text(encoding="utf-8")
        self.assertIn('"completed_stages": progress["completed_stages"]', source)
        self.assertIn('"failed_stage": None', source)
        self.assertIn('"retryable": False', source)


if __name__ == "__main__":
    unittest.main()
