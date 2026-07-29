import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets, projects, scenes, shots


class AssetProjectOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

        self.first_project = self._create_project("First")
        self.second_project = self._create_project("Second")

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

    def _create_scene(self, project_id: int):
        return scenes.create_scene({
            "project_id": project_id,
            "scene_number": 1,
            "title": "Scene",
            "status": "מתוכנן",
            "story_goal": "",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
        })

    def _create_asset(self, project_id: int, name: str):
        return assets.create_asset({
            "project_id": project_id,
            "asset_type": "אביזר",
            "name": name,
            "description": "",
        })

    def test_linked_asset_cannot_move_to_another_project(self):
        scene = self._create_scene(self.first_project["id"])
        shot = shots.create_shot({
            "project_id": self.first_project["id"],
            "scene_id": scene["id"],
            "shot_number": 1,
            "title": "Shot",
            "status": "מתוכנן",
        })
        asset = self._create_asset(self.first_project["id"], "Linked asset")
        shots.set_shot_assets(shot["id"], [asset["id"]])

        with self.assertRaisesRegex(ValueError, "מקושר לשוטים"):
            assets.update_asset(asset["id"], {
                "project_id": self.second_project["id"],
            })

        stored = assets.get_asset(asset["id"])
        self.assertEqual(stored["project_id"], self.first_project["id"])
        self.assertEqual({item["id"] for item in stored["linked_shots"]}, {shot["id"]})

    def test_unlinked_asset_can_move_to_existing_project(self):
        asset = self._create_asset(self.first_project["id"], "Movable asset")

        updated = assets.update_asset(asset["id"], {
            "project_id": self.second_project["id"],
        })

        self.assertEqual(updated["project_id"], self.second_project["id"])
        self.assertEqual(updated["linked_shots"], [])


if __name__ == "__main__":
    unittest.main()
