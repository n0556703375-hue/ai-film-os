import tempfile
import unittest
from pathlib import Path

from app.api.scenes import get_scene_preview_manifest
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots


class ScenePreviewManifestTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Assembly Test",
            "description": "",
            "visual_style": "",
            "rules": "",
        })
        self.scene = scenes.create_scene({
            "project_id": project["id"],
            "scene_number": 3,
            "title": "Assembly Scene",
            "status": "מתוכנן",
            "story_goal": "",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
        })
        self.shot_two = shots.create_shot({
            "project_id": project["id"],
            "scene_id": self.scene["id"],
            "shot_number": 2,
            "title": "Second",
            "status": "וידאו מאושר",
            "duration_seconds": 2.5,
            "audio": "room tone",
            "dialogue": "",
        })
        self.shot_one = shots.create_shot({
            "project_id": project["id"],
            "scene_id": self.scene["id"],
            "shot_number": 1,
            "title": "First",
            "status": "וידאו מאושר",
            "duration_seconds": 4,
            "audio": "",
            "dialogue": "שלום",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _approve_video(self, shot_id: int, version: int = 1):
        return shots.create_media_result(shot_id, {
            "media_type": "video",
            "url": f"https://example.com/{shot_id}-v{version}.mp4",
            "provider": "test",
            "model": "test-video",
            "version": version,
            "status": "מאושר",
        })

    def test_manifest_is_ordered_and_totals_duration(self):
        self._approve_video(self.shot_one["id"])
        self._approve_video(self.shot_two["id"])

        manifest = get_scene_preview_manifest(self.scene["id"])

        self.assertEqual([item["shot_number"] for item in manifest["timeline"]], [1, 2])
        self.assertEqual(manifest["duration_seconds"], 6.5)
        self.assertTrue(manifest["ready_for_preview"])
        self.assertTrue(manifest["timeline"][0]["has_dialogue"])
        self.assertTrue(manifest["timeline"][1]["has_audio_notes"])

    def test_manifest_reports_missing_approved_video(self):
        self._approve_video(self.shot_one["id"])

        manifest = get_scene_preview_manifest(self.scene["id"])

        self.assertFalse(manifest["ready_for_preview"])
        self.assertEqual(manifest["missing_video_shot_ids"], [self.shot_two["id"]])
        self.assertFalse(manifest["timeline"][1]["ready_for_preview"])

    def test_latest_approved_video_version_is_selected(self):
        self._approve_video(self.shot_one["id"], 1)
        self._approve_video(self.shot_one["id"], 2)

        manifest = get_scene_preview_manifest(self.scene["id"])

        self.assertTrue(manifest["timeline"][0]["video_url"].endswith("-v2.mp4"))


if __name__ == "__main__":
    unittest.main()
