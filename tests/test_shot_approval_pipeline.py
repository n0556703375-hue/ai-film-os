import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import approvals, projects, scenes, shots


class ShotApprovalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Approval Test",
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
            "status": "פרומפט מוכן",
        })
        self.image = shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/image.jpg",
            "status": "טיוטה",
        })
        self.video = shots.create_media_result(self.shot["id"], {
            "media_type": "video",
            "url": "https://example.com/video.mp4",
            "status": "טיוטה",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def test_video_requires_approved_image(self):
        with self.assertRaisesRegex(ValueError, "תמונת שוט"):
            approvals.decide_media(self.shot["id"], self.video["id"], "approve")

    def test_approval_progresses_and_finalizes_shot(self):
        pipeline = approvals.decide_media(self.shot["id"], self.image["id"], "approve", "image ok")
        self.assertEqual(pipeline["status"], "תמונה מאושרת")

        pipeline = approvals.decide_media(self.shot["id"], self.video["id"], "approve", "video ok")
        self.assertEqual(pipeline["status"], "וידאו מאושר")

        pipeline = approvals.finalize_shot(self.shot["id"], "final")
        self.assertEqual(pipeline["status"], "סופי")
        self.assertEqual(len(pipeline["approval_events"]), 3)

    def test_rejecting_approved_media_rolls_pipeline_back(self):
        approvals.decide_media(self.shot["id"], self.image["id"], "approve")
        pipeline = approvals.decide_media(self.shot["id"], self.image["id"], "reject", "redo")
        self.assertEqual(pipeline["status"], "וידאו טיוטה")
        image = next(item for item in pipeline["media_results"] if item["id"] == self.image["id"])
        self.assertEqual(image["status"], "נדחה")


if __name__ == "__main__":
    unittest.main()
