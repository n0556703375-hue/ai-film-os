import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.generation import magnific_task
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots


class ImageGenerationPollingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Polling Test",
            "description": "",
            "visual_style": "",
            "rules": "",
        })
        scene = scenes.create_scene({
            "project_id": project["id"],
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
        self.shot = shots.create_shot({
            "project_id": project["id"],
            "scene_id": scene["id"],
            "shot_number": 1,
            "title": "Shot",
            "prompt": "A production-ready image prompt",
            "status": "פרומפט מוכן",
        })
        shots.save_prompt_version(
            self.shot["id"],
            self.shot["prompt"],
            "",
            "test",
        )

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    @patch("app.api.generation.get_magnific_image")
    def test_completed_poll_creates_one_image_and_sets_draft_status(self, get_task):
        get_task.return_value = {
            "task_id": "task-123",
            "status": "COMPLETED",
            "generated": ["https://example.com/generated.jpg"],
            "has_nsfw": [False],
        }

        first = magnific_task(self.shot["id"], "task-123")
        second = magnific_task(self.shot["id"], "task-123")

        self.assertEqual(first["media"]["id"], second["media"]["id"])
        self.assertEqual(len(shots.list_media_results(self.shot["id"])), 1)
        self.assertEqual(shots.get_shot(self.shot["id"])["status"], "תמונת טיוטה")
        self.assertEqual(first["media"]["metadata"]["magnific_task_id"], "task-123")


if __name__ == "__main__":
    unittest.main()
