import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api.video_generation import VideoQueueRequest, queue_video
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import jobs, projects, scenes, shots


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


if __name__ == "__main__":
    unittest.main()
