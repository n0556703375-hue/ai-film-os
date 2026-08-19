"""Coverage for the missing piece that made the identity-drift AI check a
dead end in production: nothing ever marked a fresh media_result as
"pending" for assessment. app.repositories.shots.create_media_result now
does this automatically — for both image and video — whenever the shot has
a locked character master to compare against.
"""

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.core.config import settings
from app.database.connection import get_connection, init_db
from app.repositories import assets as assets_repo
from app.repositories import projects, scenes, shots


class IdentityDriftAutoQueueTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = projects.create_project(
            {"name": "AutoQueue", "description": "", "visual_style": "", "rules": ""}
        )
        scene = scenes.create_scene({
            "project_id": self.project["id"], "scene_number": 1, "title": "S",
            "status": "מתוכנן", "story_goal": "", "emotion": "", "conflict": "",
            "beginning": "", "ending": "", "notes": "",
        })
        self.shot = shots.create_shot({
            "project_id": self.project["id"], "scene_id": scene["id"],
            "shot_number": 1, "title": "Shot",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _lock_character_on_shot(self):
        character = assets_repo.create_asset({
            "project_id": self.project["id"], "asset_type": "דמות", "name": "גיבורה",
        })
        with closing(get_connection()) as conn:
            conn.execute(
                "UPDATE assets SET lock_status='locked' WHERE id=?", (character["id"],)
            )
            conn.commit()
        shots.set_shot_assets(self.shot["id"], [character["id"]])

    def test_image_result_is_queued_when_shot_has_locked_character(self):
        self._lock_character_on_shot()
        media = shots.create_media_result(self.shot["id"], {
            "media_type": "image", "url": "https://example.com/x.png", "status": "טיוטה",
        })
        self.assertEqual(media["metadata"]["identity_drift"]["status"], "pending")
        self.assertEqual(media["metadata"]["identity_drift"]["attempt"], 0)

    def test_video_result_is_queued_when_shot_has_locked_character(self):
        self._lock_character_on_shot()
        media = shots.create_media_result(self.shot["id"], {
            "media_type": "video", "url": "https://example.com/x.mp4", "status": "טיוטה",
        })
        self.assertEqual(media["metadata"]["identity_drift"]["status"], "pending")

    def test_not_queued_when_shot_has_no_locked_character(self):
        media = shots.create_media_result(self.shot["id"], {
            "media_type": "image", "url": "https://example.com/x.png", "status": "טיוטה",
        })
        self.assertNotIn("identity_drift", media["metadata"])

    def test_explicit_metadata_identity_drift_is_never_overwritten(self):
        self._lock_character_on_shot()
        media = shots.create_media_result(self.shot["id"], {
            "media_type": "image", "url": "https://example.com/x.png", "status": "טיוטה",
            "metadata": {"identity_drift": {"status": "passed", "passed": True}},
        })
        self.assertEqual(media["metadata"]["identity_drift"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
