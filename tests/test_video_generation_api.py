import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api.video_generation import VideoQueueRequest, queue_video
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import jobs, projects, scenes, shots
from app.services.video_model_selector import select_video_model


class VideoGenerationApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Video Controls",
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
            "prompt": "Cinematic shot prompt",
            "movement": "slow push in",
            "status": "תמונה מאושרת",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def test_requires_approved_image(self):
        with self.assertRaises(HTTPException) as raised:
            queue_video(self.shot["id"], VideoQueueRequest())
        self.assertEqual(raised.exception.status_code, 409)

    def test_controls_are_persisted_and_duplicate_request_is_reused(self):
        image = shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/approved.jpg",
            "status": "מאושר",
        })
        request = VideoQueueRequest(
            duration_seconds=8,
            camera_motion="orbit left",
            audio_mode="ambient",
            aspect_ratio="16:9",
            model_hint="cinematic",
            instructions="Preserve facial identity",
        )

        first = queue_video(self.shot["id"], request)
        second = queue_video(self.shot["id"], request)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["job"]["id"], second["job"]["id"])
        payload = first["job"]["payload"]
        self.assertEqual(payload["source_image_media_id"], image["id"])
        self.assertEqual(payload["duration_seconds"], 8)
        self.assertEqual(payload["camera_motion"], "orbit left")
        self.assertEqual(payload["audio_mode"], "ambient")
        self.assertEqual(payload["model_hint"], "cinematic")
        self.assertEqual(len(jobs.list_jobs(shot_id=self.shot["id"])), 1)

    def test_stored_model_profile_matches_what_the_worker_will_select(self):
        shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/approved.jpg",
            "status": "מאושר",
        })
        request = VideoQueueRequest(
            duration_seconds=10,
            camera_motion="handheld chase",
            audio_mode="none",
        )

        result = queue_video(self.shot["id"], request)

        payload = result["job"]["payload"]
        shot = shots.get_shot(self.shot["id"])
        worker_time_selection = select_video_model(shot, payload)
        self.assertEqual(payload["selected_model_profile"], worker_time_selection.profile)
        self.assertEqual(payload["model_selection_reason"], worker_time_selection.reason)


if __name__ == "__main__":
    unittest.main()
