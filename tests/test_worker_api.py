import tempfile
import unittest
from pathlib import Path

from app.api.worker import get_worker_status, trigger_next_job
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import jobs, projects, scenes, shots
from app.repositories.approvals import APPROVED
import app.background_worker as background_worker


class WorkerApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project(
            {"name": "WorkerAPI", "description": "", "visual_style": "", "rules": ""}
        )
        scene = scenes.create_scene(
            {
                "project_id": project["id"],
                "scene_number": 1,
                "title": "S",
                "status": "מתוכנן",
                "story_goal": "",
                "emotion": "",
                "conflict": "",
                "beginning": "",
                "ending": "",
                "notes": "",
            }
        )
        self.project_id = project["id"]
        self.shot = shots.create_shot(
            {
                "project_id": project["id"],
                "scene_id": scene["id"],
                "shot_number": 1,
                "title": "Shot",
                "prompt": "a wide establishing shot",
                "duration_seconds": 5,
            }
        )
        shots.create_media_result(
            self.shot["id"],
            {
                "media_type": "image",
                "url": "https://cdn.example/approved.png",
                "status": APPROVED,
            },
        )
        background_worker._worker_thread = None
        background_worker._last_job_timestamp = None
        background_worker._last_job_shot_id = None
        background_worker._jobs_processed_count = 0
        background_worker._stop_event.clear()

    def tearDown(self):
        background_worker.stop()
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _enqueue_video(self, key="shot-1-video-v1"):
        job, _ = jobs.enqueue_job(
            self.project_id, self.shot["id"], "video", {}, key, max_attempts=3
        )
        return job

    def test_status_endpoint_reports_shape(self):
        status = get_worker_status()
        self.assertIn("alive", status)
        self.assertIn("thread_id", status)
        self.assertIn("last_job_timestamp", status)
        self.assertIn("last_job_shot_id", status)
        self.assertIn("jobs_processed", status)
        self.assertIn("queued_job_count", status)

    def test_status_endpoint_reflects_started_thread(self):
        self.assertFalse(get_worker_status()["alive"])
        background_worker.start()
        self.assertTrue(get_worker_status()["alive"])

    def test_process_next_endpoint_processes_queued_job(self):
        self._enqueue_video()
        result = trigger_next_job()
        # No provider configured in test env -> job fails, but the endpoint
        # must still claim and process exactly one queued job.
        self.assertEqual(result["status"], "failed")
        self.assertEqual(get_worker_status()["queued_job_count"], 0)

    def test_process_next_endpoint_empty_queue_returns_empty_dict(self):
        result = trigger_next_job()
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
