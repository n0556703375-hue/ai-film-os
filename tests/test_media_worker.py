import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import jobs, projects, scenes, shots
from app.services.video_provider import VideoGenerationResult
from app.worker import process_one_job

import app.worker as worker


class MediaWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self._real_sleep = worker.time.sleep
        worker.time.sleep = lambda *_a, **_k: None
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
            "duration_seconds": 6,
            "movement": "slow push in",
        })
        self.project_id = project["id"]

    def tearDown(self):
        worker.time.sleep = self._real_sleep
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    @patch("app.worker.validate_generated_image")
    @patch("app.worker._wait_for_image_task")
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

    def test_video_job_requires_approved_image(self):
        jobs.enqueue_job(
            self.project_id,
            self.shot["id"],
            "video",
            {},
            "worker-video-no-image",
            max_attempts=3,
        )

        failed = process_one_job("test-worker")

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempts"], 1)
        self.assertIn("לאשר תמונת שוט", failed["last_error"])

    @patch("app.worker.get_video_provider")
    def test_video_job_uses_provider_contract_and_creates_media(self, get_provider):
        shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/approved.jpg",
            "provider": "Magnific",
            "model": "Nano Banana Pro",
            "status": "מאושר",
        })
        # spec=["generate"] matters: a bare Mock() auto-creates any attribute
        # accessed on it (including submit/check_task), which would silently
        # route this "simple generate()-only provider" test through the
        # resumable submit/check_task path instead of the fallback branch it
        # means to exercise.
        provider = Mock(spec=["generate", "name"])
        provider.name = "test-video"
        provider.generate.return_value = VideoGenerationResult(
            url="https://example.com/result.mp4",
            provider="Test Video",
            model="test-i2v",
            external_task_id="video-task-1",
            actual_cost_usd=0.42,
        )
        get_provider.return_value = provider
        jobs.enqueue_job(
            self.project_id,
            self.shot["id"],
            "video",
            {"audio_mode": "none", "aspect_ratio": "16:9", "model_hint": "auto"},
            "worker-video-success",
        )

        completed = process_one_job("test-worker")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["actual_cost_usd"], 0.42)
        self.assertEqual(completed["result"]["model_profile"], "cinematic")
        media = shots.list_media_results(self.shot["id"])
        video = next(item for item in media if item["media_type"] == "video")
        self.assertEqual(video["url"], "https://example.com/result.mp4")
        self.assertEqual(video["metadata"]["provider_task_id"], "video-task-1")
        self.assertEqual(video["metadata"]["model_profile"], "cinematic")
        self.assertIn("balanced default", video["metadata"]["model_selection_reason"])
        self.assertEqual(shots.get_shot(self.shot["id"])["status"], "וידאו טיוטה")
        request = provider.generate.call_args.args[0]
        self.assertEqual(request.image_url, "https://example.com/approved.jpg")
        self.assertEqual(request.duration_seconds, 6)
        self.assertEqual(request.camera_motion, "slow push in")
        self.assertEqual(request.model_profile, "cinematic")

    def test_empty_queue_returns_none(self):
        self.assertIsNone(process_one_job("test-worker"))

    @patch("app.services.providers.local_comfyui_image_provider.LocalComfyUIImageProvider")
    @patch("app.services.providers.comfyui_client.is_configured", return_value=True)
    def test_draft_mode_image_job_uses_local_comfyui_provider(self, _is_configured, provider_cls):
        provider = Mock()
        provider.submit.return_value = {
            "task_id": "local-img-1", "status": "IN_PROGRESS",
            "provider": "local_comfyui_image", "model": "sdxl-1.0",
        }
        provider.check_task.return_value = {
            "task_id": "local-img-1", "status": "COMPLETED",
            "generated": ["/generated/uploads/shot-1/local.png"], "has_nsfw": [False],
        }
        provider_cls.return_value = provider

        jobs.enqueue_job(
            self.project_id, self.shot["id"], "image",
            {"draft_mode": True, "local_model": "sdxl"}, "worker-draft-image-1",
        )

        completed = process_one_job("test-worker")

        self.assertEqual(completed["status"], "completed")
        media = shots.list_media_results(self.shot["id"])
        self.assertEqual(media[0]["url"], "/generated/uploads/shot-1/local.png")
        provider.submit.assert_called_once()
        self.assertEqual(provider.submit.call_args.kwargs["model"], "sdxl")

    @patch("app.services.providers.comfyui_client.is_configured", return_value=False)
    def test_draft_mode_image_job_without_comfyui_configured_fails_non_retryable(self, _is_configured):
        jobs.enqueue_job(
            self.project_id, self.shot["id"], "image",
            {"draft_mode": True}, "worker-draft-image-unconfigured",
        )

        failed = process_one_job("test-worker")

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempts"], 1)
        self.assertIn("COMFYUI_ENDPOINT", failed["last_error"])

    @patch("app.worker.persist_remote_video")
    @patch("app.worker.get_video_provider")
    def test_draft_mode_video_job_allows_private_host_persistence(self, get_provider, persist):
        shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/approved.jpg",
            "provider": "Magnific",
            "model": "Nano Banana Pro",
            "status": "מאושר",
        })
        provider = Mock(spec=["submit", "check_task", "model_for", "cost_for", "name", "trusted_local"])
        provider.name = "local_comfyui"
        provider.trusted_local = True
        provider.submit.return_value = "local-video-task-1"
        provider.check_task.return_value = {"status": "succeed", "url": "http://localhost:8188/view?filename=out.mp4"}
        provider.model_for.return_value = "wan-2.2-14b"
        provider.cost_for.return_value = 0.0
        get_provider.return_value = provider
        persist.return_value = {"url": "/generated/videos/shot-1/local.mp4", "size_bytes": 10, "content_type": "video/mp4"}

        jobs.enqueue_job(
            self.project_id, self.shot["id"], "video",
            {"draft_mode": True, "local_model": "wan"}, "worker-draft-video-1",
        )

        completed = process_one_job("test-worker")

        self.assertEqual(completed["status"], "completed")
        get_provider.assert_called_once_with(draft_mode=True)
        persist.assert_called_once_with(
            "http://localhost:8188/view?filename=out.mp4", self.shot["id"], allow_private_host=True,
        )


if __name__ == "__main__":
    unittest.main()
