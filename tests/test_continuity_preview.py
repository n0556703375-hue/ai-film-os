import tempfile
import unittest
from pathlib import Path

from app.api.issues import preview_shot_continuity
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets, projects, scenes, shots


class ContinuityPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({"name": "Continuity", "description": "", "visual_style": "", "rules": ""})
        scene = scenes.create_scene({
            "project_id": project["id"], "scene_number": 1, "title": "Scene", "status": "מתוכנן",
            "story_goal": "", "emotion": "", "conflict": "", "beginning": "", "ending": "", "notes": "",
        })
        self.project_id = project["id"]
        self.scene_id = scene["id"]

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _shot(self, number: int, **fields):
        payload = {
            "project_id": self.project_id, "scene_id": self.scene_id, "shot_number": number,
            "title": f"Shot {number}", "status": "מתוכנן", "lighting": "cool daylight",
            "movement": "locked camera", "shot_type": "Medium",
        }
        payload.update(fields)
        return shots.create_shot(payload)

    def test_preview_compares_previous_and_next_without_writing_issues(self):
        first = self._shot(1)
        middle = self._shot(2)
        third = self._shot(3, lighting="warm practical light")

        preview = preview_shot_continuity(middle["id"])

        self.assertEqual(preview["previous_shot_id"], first["id"])
        self.assertEqual(preview["next_shot_id"], third["id"])
        self.assertTrue(any(issue["category"] == "lighting" and issue["relation"] == "הבא" for issue in preview["issues"]))
        self.assertEqual(preview["blocking_issue_count"], 0)
        self.assertTrue(preview["can_finalize"])

    def test_missing_character_in_neighbor_is_reported_as_blocking(self):
        first = self._shot(1)
        middle = self._shot(2)
        character = assets.create_asset({
            "project_id": self.project_id, "asset_type": "דמות", "name": "ליאורה",
            "description": "", "visual_rules": "", "master_prompt": "", "negative_prompt": "",
            "reference_url": "", "approved": True,
        })
        shots.set_shot_assets(middle["id"], [character["id"]])

        preview = preview_shot_continuity(middle["id"])

        issue = next(item for item in preview["issues"] if item.get("asset_id") == character["id"])
        self.assertEqual(issue["severity"], "high")
        self.assertEqual(issue["neighbor_shot_id"], first["id"])
        self.assertEqual(preview["blocking_issue_count"], 1)
        self.assertFalse(preview["can_finalize"])


if __name__ == "__main__":
    unittest.main()
