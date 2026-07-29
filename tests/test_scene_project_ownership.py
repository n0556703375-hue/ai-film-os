import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots


class SceneProjectOwnershipTests(unittest.TestCase):
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

    def _create_scene(self, project_id: int, title: str):
        return scenes.create_scene({
            "project_id": project_id,
            "scene_number": 1,
            "title": title,
            "status": "מתוכנן",
            "story_goal": "",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
        })

    def test_scene_with_shots_cannot_move_to_another_project(self):
        scene = self._create_scene(self.first_project["id"], "First scene")
        shot = shots.create_shot({
            "project_id": self.first_project["id"],
            "scene_id": scene["id"],
            "shot_number": 1,
            "title": "First shot",
            "status": "מתוכנן",
        })

        with self.assertRaisesRegex(ValueError, "סצנה עם שוטים"):
            scenes.update_scene(scene["id"], {
                "project_id": self.second_project["id"],
            })

        stored_scene = scenes.get_scene(scene["id"])
        stored_shot = shots.get_shot(shot["id"])
        self.assertEqual(stored_scene["project_id"], self.first_project["id"])
        self.assertEqual(stored_shot["project_id"], self.first_project["id"])
        self.assertEqual(stored_shot["scene_id"], scene["id"])

    def test_empty_scene_can_move_to_an_existing_project(self):
        scene = self._create_scene(self.first_project["id"], "Movable scene")

        updated = scenes.update_scene(scene["id"], {
            "project_id": self.second_project["id"],
        })

        self.assertEqual(updated["project_id"], self.second_project["id"])
        self.assertEqual(updated["shots"], [])


if __name__ == "__main__":
    unittest.main()
