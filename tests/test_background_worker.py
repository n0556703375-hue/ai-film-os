import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import jobs, projects, scenes, shots
from app.repositories.approvals import APPROVED
import app.background_worker as background_worker


class BackgroundWorkerStatusTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project(
            {"name": "BG", "description": "", "visual_style": "", "rules": ""}
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

        # Reset module-level state between tests since it's a singleton.
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

    def test_status_reports_not_alive_before_start(self):
        status = background_worker.get_status()
        self.assertFalse(status["alive"])
        self.assertIsNone(status["last_job_timestamp"])
        self.assertIsNone(status["last_job_shot_id"])
        self.assertEqual(status["jobs_processed"], 0)

    def test_status_counts_queued_jobs(self):
        self._enqueue_video()
        status = background_worker.get_status()
        self.assertEqual(status["queued_job_count"], 1)

    def test_process_next_job_with_no_provider_fails_job(self):
        # No FAL_API_KEY / Kling keys configured -> DisabledVideoProvider.
        self._enqueue_video()
        result = background_worker.process_next_job()
        self.assertEqual(result["status"], "failed")

    def test_process_next_job_returns_empty_when_queue_empty(self):
        result = background_worker.process_next_job()
        self.assertEqual(result, {})

    def test_start_launches_daemon_thread(self):
        background_worker.start()
        self.assertTrue(background_worker.is_alive())
        self.assertTrue(background_worker._worker_thread.daemon)

    def test_start_is_idempotent_when_already_running(self):
        background_worker.start()
        first_thread = background_worker._worker_thread
        background_worker.start()
        self.assertIs(background_worker._worker_thread, first_thread)

    def test_stop_terminates_thread(self):
        background_worker.start()
        self.assertTrue(background_worker.is_alive())
        background_worker.stop()
        self.assertFalse(background_worker.is_alive())

    def test_identity_assessment_skipped_when_openai_not_configured(self):
        original_key = settings.openai_api_key
        settings.openai_api_key = ""
        try:
            with patch("app.background_worker.process_next_identity_assessment") as mock_process:
                result = background_worker._process_next_identity_assessment_safely("w1")
        finally:
            settings.openai_api_key = original_key
        mock_process.assert_not_called()
        self.assertFalse(result)

    def test_identity_assessment_processed_when_configured(self):
        original_key = settings.openai_api_key
        settings.openai_api_key = "test-key"
        try:
            with patch(
                "app.background_worker.process_next_identity_assessment",
                return_value={"processed": True, "shot_id": 1, "media_id": 2},
            ) as mock_process:
                result = background_worker._process_next_identity_assessment_safely("w1")
        finally:
            settings.openai_api_key = original_key
        mock_process.assert_called_once_with(worker_id="w1")
        self.assertTrue(result)

    def test_identity_assessment_failure_is_swallowed(self):
        original_key = settings.openai_api_key
        settings.openai_api_key = "test-key"
        try:
            with patch(
                "app.background_worker.process_next_identity_assessment",
                side_effect=RuntimeError("provider down"),
            ):
                result = background_worker._process_next_identity_assessment_safely("w1")
        finally:
            settings.openai_api_key = original_key
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
