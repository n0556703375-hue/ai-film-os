import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import approvals, issues, projects, scenes, shots


class TwoProjectFinalizationIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_ready_shot(self, project_name: str, media_suffix: str):
        project = projects.create_project({
            "name": project_name,
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
        shot = shots.create_shot({
            "project_id": project["id"],
            "scene_id": scene["id"],
            "shot_number": 1,
            "title": "Shot",
            "status": "פרומפט מוכן",
        })
        image = shots.create_media_result(shot["id"], {
            "media_type": "image",
            "url": f"https://example.com/{media_suffix}.jpg",
            "status": "טיוטה",
        })
        video = shots.create_media_result(shot["id"], {
            "media_type": "video",
            "url": f"https://example.com/{media_suffix}.mp4",
            "status": "טיוטה",
        })
        approvals.decide_media(shot["id"], image["id"], "approve", project["id"])
        approvals.decide_media(shot["id"], video["id"], "approve", project["id"])
        return project, shot

    def test_foreign_blocking_issue_cannot_block_or_mutate_other_project_finalization(self):
        first_project, first_shot = self._create_ready_shot("First Production", "first")
        other_project, other_shot = self._create_ready_shot("Other Production", "other")

        issues.create_issue({
            "project_id": other_project["id"],
            "shot_id": other_shot["id"],
            "severity": "critical",
            "category": "continuity",
            "message": "Foreign project blocker",
            "status": "פתוח",
        })

        first_preview = approvals.preview_batch_finalize([first_shot["id"]], first_project["id"])
        self.assertEqual(first_preview["eligible"], 1)
        self.assertTrue(first_preview["items"][0]["eligible"])

        finalized = approvals.finalize_shot(first_shot["id"], first_project["id"], "first project final")
        self.assertEqual(finalized["status"], "סופי")
        self.assertEqual(
            [event["event_type"] for event in finalized["approval_events"]].count("shot_finalized"),
            1,
        )

        other_preview = approvals.preview_batch_finalize([other_shot["id"]], other_project["id"])
        self.assertEqual(other_preview["eligible"], 0)
        self.assertFalse(other_preview["items"][0]["eligible"])
        self.assertIn("קיימת בעיית רציפות חוסמת.", other_preview["items"][0]["reasons"])

        other_pipeline = approvals.get_pipeline(other_shot["id"])
        self.assertEqual(other_pipeline["status"], "וידאו מאושר")
        self.assertFalse(any(
            event["event_type"] == "shot_finalized"
            for event in other_pipeline["approval_events"]
        ))
        self.assertNotEqual(first_project["id"], other_project["id"])

    def test_finalize_actions_reject_a_shot_id_from_another_project(self):
        first_project, first_shot = self._create_ready_shot("First Production", "first")
        other_project, other_shot = self._create_ready_shot("Other Production", "other")

        cross_project_preview = approvals.preview_batch_finalize(
            [other_shot["id"]], first_project["id"]
        )
        self.assertFalse(cross_project_preview["items"][0]["eligible"])
        self.assertIn("השוט לא נמצא.", cross_project_preview["items"][0]["reasons"])

        result = approvals.finalize_shot(other_shot["id"], first_project["id"])
        self.assertIsNone(result)

        other_pipeline = approvals.get_pipeline(other_shot["id"])
        self.assertNotEqual(other_pipeline["status"], "סופי")


if __name__ == "__main__":
    unittest.main()
