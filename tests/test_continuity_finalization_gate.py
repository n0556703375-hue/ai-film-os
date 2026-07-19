import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import approvals, issues, projects, scenes, shots


class ContinuityFinalizationGateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Continuity Gate Test",
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
        self.project_id = project["id"]
        self.shot = shots.create_shot({
            "project_id": project["id"],
            "scene_id": scene["id"],
            "shot_number": 1,
            "title": "Shot",
            "prompt": "Locked prompt",
            "status": "וידאו מאושר",
        })
        shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/image.jpg",
            "provider": "test",
            "model": "test-image",
            "status": "מאושר",
        })
        shots.create_media_result(self.shot["id"], {
            "media_type": "video",
            "url": "https://example.com/video.mp4",
            "provider": "test",
            "model": "test-video",
            "status": "מאושר",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _issue(self, severity: str, status: str = "פתוח"):
        return issues.create_issue({
            "project_id": self.project_id,
            "shot_id": self.shot["id"],
            "severity": severity,
            "category": "continuity",
            "message": f"{severity} mismatch",
            "status": status,
        })

    def test_high_issue_blocks_finalization(self):
        self._issue("high")

        with self.assertRaises(ValueError) as raised:
            approvals.finalize_shot(self.shot["id"])

        self.assertIn("בחומרה גבוהה", str(raised.exception))
        self.assertNotEqual(shots.get_shot(self.shot["id"])["status"], "סופי")

    def test_resolved_high_issue_allows_finalization(self):
        issue = self._issue("high")
        issues.resolve_issue(issue["id"], True)

        pipeline = approvals.finalize_shot(self.shot["id"], "continuity cleared")

        self.assertEqual(pipeline["status"], "סופי")

    def test_approved_exception_allows_finalization(self):
        self._issue("critical", "אושר כחריגה")

        pipeline = approvals.finalize_shot(self.shot["id"])

        self.assertEqual(pipeline["status"], "סופי")

    def test_medium_issue_does_not_block_finalization(self):
        self._issue("medium")

        pipeline = approvals.finalize_shot(self.shot["id"])

        self.assertEqual(pipeline["status"], "סופי")


if __name__ == "__main__":
    unittest.main()
