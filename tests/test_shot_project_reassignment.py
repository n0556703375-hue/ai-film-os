import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets, projects, scenes, shots


class ShotProjectReassignmentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

        self.first_project = self._create_project("First")
        self.second_project = self._create_project("Second")
        self.scene = scenes.create_scene({
            "project_id": self.first_project["id"],
            "scene_number": 1,
            "title": "First scene",
            "status": "מתוכנן",
            "story_goal": "",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
        })
        self.shot = shots.create_shot({
            "project_id": self.first_project["id"],
            "scene_id": self.scene["id"],
            "shot_number": 1,
            "title": "First shot",
            "status": "מתוכנן",
        })
        self.asset = assets.create_asset({
            "project_id": self.first_project["id"],
            "asset_type": "אביזר",
            "name": "First prop",
            "description": "",
        })
        shots.set_shot_assets(self.shot["id"], [self.asset["id"]])

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_project(self, name: str):
        return projects.create_project({
            "name": name,
            "description": "",
            "visual_style": "",
            "rules": "",
        })

    def test_linked_shot_cannot_be_reassigned_to_another_project(self):
        with self.assertRaisesRegex(ValueError, "פרויקט"):
            shots.update_shot(self.shot["id"], {
                "project_id": self.second_project["id"],
            })

        stored = shots.get_shot(self.shot["id"])
        self.assertEqual(stored["project_id"], self.first_project["id"])
        self.assertEqual(stored["scene_id"], self.scene["id"])
        self.assertEqual(
            {asset["id"] for asset in stored["assets"]},
            {self.asset["id"]},
        )


if __name__ == "__main__":
    unittest.main()
