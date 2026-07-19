import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import jobs, projects, scenes, shots
from app.worker import process_one_job


class MediaWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Worker Test",
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
            "prompt": "A locked production prompt",
            "status": "פרומפט מוכן",
        })
        self.project_id = project["id"]

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    @patch("app.worker.validate_generated_image")
    @patch("app.worker._wait_for_magnific")
    @patch("app.worker.submit_magnific_image")
    def test_image_job_creates_media_and_completes(self, submit, wait, validate):
        submit.return_value = {
            "task_id": "task-worker-1",
            "provider": "Magnific",
            "model": "Nano Banana Pro",
        }
        wait.return_value = {
            "status": "COMPLETED",
            "generated": ["https://example.com/result.jpg"],
            "has_nsfw": [False],
        }
        queued, _ = jobs.enqueue_job(
            self.project_id,
            self.shot["id"],
            "image",
            {"aspect_ratio": "16:9"},
            "worker-image-1",
        )

        completed = process_one_job("test-worker")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["provider_task_id"], "task-worker-1")
        media = shots.list_media_results(self.shot["id"])
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["metadata"]["media_job_id"], queued["id"])
        self.assertEqual(shots.get_shot(self.shot["id"])["status"], "תמונת טיוטה")
        validate.assert_called_once_with("https://example.com/result.jpg")

    def test_video_job_fails_without_retry(self):
        jobs.enqueue_job(
            self.project_id,
            self.shot["id"],
            "video",
            {},
            "worker-video-1",
            max_attempts=3,
        )

        failed = process_one_job("test-worker")

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempts"], 1)
        self.assertIn("Video worker", failed["last_error"])

    def test_empty_queue_returns_none(self):
        self.assertIsNone(process_one_job("test-worker"))


if __name__ == "__main__":
    unittest.main()
