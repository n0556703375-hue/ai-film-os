"""Coverage for GET /api/video-generation/shots/{shot_id}/readiness.

This endpoint must never trigger a paid provider submission — every test
here proves that in addition to the reported readiness booleans.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.video_generation import get_shot_readiness
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots
from app.repositories.approvals import APPROVED
from app.services.public_media_url import PublicMediaUrlError
from app.services.video_provider import DisabledVideoProvider


class ShotReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        self.original_fal_key = settings.fal_api_key
        self.original_kling_access = settings.kling_access_key
        self.original_kling_secret = settings.kling_secret_key
        # get_video_provider() (app/services/video_provider.py) reads the raw
        # environment directly rather than `settings`, so both must be
        # controlled here for provider_configured to be deterministic.
        self.original_fal_api_key_env = os.environ.get("FAL_API_KEY")
        self.original_kling_access_env = os.environ.get("KLING_ACCESS_KEY")
        self.original_kling_secret_env = os.environ.get("KLING_SECRET_KEY")
        settings.database_path = Path(self.tempdir.name) / "test.db"
        settings.fal_api_key = ""
        settings.kling_access_key = ""
        settings.kling_secret_key = ""
        os.environ.pop("FAL_API_KEY", None)
        os.environ.pop("KLING_ACCESS_KEY", None)
        os.environ.pop("KLING_SECRET_KEY", None)
        init_db()
        project = projects.create_project(
            {"name": "Readiness", "description": "", "visual_style": "", "rules": ""}
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
        self.shot = shots.create_shot(
            {
                "project_id": project["id"],
                "scene_id": scene["id"],
                "shot_number": 1,
                "title": "Shot",
                "prompt": "",
                "duration_seconds": 5,
            }
        )

    def tearDown(self):
        settings.database_path = self.original_db
        settings.fal_api_key = self.original_fal_key
        settings.kling_access_key = self.original_kling_access
        settings.kling_secret_key = self.original_kling_secret
        for key, value in (
            ("FAL_API_KEY", self.original_fal_api_key_env),
            ("KLING_ACCESS_KEY", self.original_kling_access_env),
            ("KLING_SECRET_KEY", self.original_kling_secret_env),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tempdir.cleanup()

    def _configure_fal_key(self):
        os.environ["FAL_API_KEY"] = "test-key"
        settings.fal_api_key = "test-key"

    def test_missing_shot_returns_404(self):
        with self.assertRaises(HTTPException) as ctx:
            get_shot_readiness(999999)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_no_approved_image_reports_not_ready(self):
        result = get_shot_readiness(self.shot["id"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["approved_image"])
        self.assertIn("no_approved_image", result["reasons"])

    def test_never_submits_to_provider_even_when_everything_is_configured(self):
        self._configure_fal_key()
        shots.create_media_result(
            self.shot["id"],
            {"media_type": "image", "url": "https://cdn.example/approved.png", "status": APPROVED},
        )
        with patch("app.api.video_generation.preflight_check_public_image"), \
             patch("app.background_worker.is_alive", return_value=True), \
             patch("app.services.seedance_provider.fal_client.submit") as mock_submit:
            result = get_shot_readiness(self.shot["id"])
        mock_submit.assert_not_called()
        self.assertTrue(result["ready"])

    def test_unreachable_image_reports_not_publicly_accessible(self):
        shots.create_media_result(
            self.shot["id"],
            {"media_type": "image", "url": "https://cdn.example/approved.png", "status": APPROVED},
        )
        with patch(
            "app.api.video_generation.preflight_check_public_image",
            side_effect=PublicMediaUrlError(PublicMediaUrlError.UNREACHABLE),
        ):
            result = get_shot_readiness(self.shot["id"])
        self.assertFalse(result["ready"])
        self.assertTrue(result["approved_image"])
        self.assertFalse(result["image_publicly_accessible"])
        self.assertIn("image_not_publicly_accessible:unreachable", result["reasons"])

    def test_provider_not_configured_is_reported(self):
        shots.create_media_result(
            self.shot["id"],
            {"media_type": "image", "url": "https://cdn.example/approved.png", "status": APPROVED},
        )
        with patch("app.api.video_generation.preflight_check_public_image"):
            result = get_shot_readiness(self.shot["id"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["provider_configured"])
        self.assertIn("provider_not_configured", result["reasons"])

    def test_worker_not_alive_is_reported(self):
        self._configure_fal_key()
        shots.create_media_result(
            self.shot["id"],
            {"media_type": "image", "url": "https://cdn.example/approved.png", "status": APPROVED},
        )
        with patch("app.api.video_generation.preflight_check_public_image"), \
             patch("app.background_worker.is_alive", return_value=False):
            result = get_shot_readiness(self.shot["id"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["worker_alive"])
        self.assertIn("worker_not_alive", result["reasons"])

    def test_all_conditions_green_reports_ready_with_no_reasons(self):
        self._configure_fal_key()
        shots.create_media_result(
            self.shot["id"],
            {"media_type": "image", "url": "https://cdn.example/approved.png", "status": APPROVED},
        )
        with patch("app.api.video_generation.preflight_check_public_image"), \
             patch("app.background_worker.is_alive", return_value=True):
            result = get_shot_readiness(self.shot["id"])
        self.assertEqual(
            result,
            {
                "ready": True,
                "approved_image": True,
                "image_publicly_accessible": True,
                "provider_configured": True,
                "worker_alive": True,
                "reasons": [],
            },
        )

    def test_disabled_provider_alone_blocks_readiness(self):
        # DisabledVideoProvider must count as "not configured", not crash.
        shots.create_media_result(
            self.shot["id"],
            {"media_type": "image", "url": "https://cdn.example/approved.png", "status": APPROVED},
        )
        with patch("app.api.video_generation.preflight_check_public_image"), \
             patch(
                 "app.api.video_generation.get_video_provider",
                 return_value=DisabledVideoProvider(),
             ):
            result = get_shot_readiness(self.shot["id"])
        self.assertFalse(result["provider_configured"])


if __name__ == "__main__":
    unittest.main()
