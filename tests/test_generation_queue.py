import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api.generation import queue_for_shot
from app.core.config import settings
from app.database.connection import init_db
from app.models.schemas import GenerationRequest
from app.repositories import jobs, projects, scenes, shots


class GenerationQueueTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Queue UI Test",
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
        self.project_id = project["id"]
        self.scene_id = scene["id"]

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_shot(self, prompt: str):
        return shots.create_shot({
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "shot_number": 1,
            "title": "Shot",
            "prompt": prompt,
            "status": "פרומפט מוכן",
        })

    def test_same_request_reuses_durable_job(self):
        shot = self._create_shot("A production-ready prompt")
        request = GenerationRequest(
            media_type="image",
            instructions="",
            size="1536x1024",
            quality="medium",
        )

        first = queue_for_shot(shot["id"], request)
        second = queue_for_shot(shot["id"], request)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["job"]["id"], second["job"]["id"])
        self.assertEqual(first["job"]["status"], "queued")
        self.assertEqual(first["job"]["payload"]["aspect_ratio"], "16:9")
        self.assertEqual(len(jobs.list_jobs(shot_id=shot["id"])), 1)

    def test_queue_requires_prompt(self):
        shot = self._create_shot("")
        request = GenerationRequest(media_type="image")

        with self.assertRaises(HTTPException) as raised:
            queue_for_shot(shot["id"], request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("פרומפט", raised.exception.detail)

    def test_queue_rejects_video_until_provider_is_selected(self):
        shot = self._create_shot("A production-ready prompt")
        request = GenerationRequest(media_type="video")

        with self.assertRaises(HTTPException) as raised:
            queue_for_shot(shot["id"], request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("תמונה בלבד", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
