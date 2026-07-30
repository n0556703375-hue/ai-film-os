import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api.identity_assessments import (
    list_completed_identity_drift,
    list_pending_identity_drift,
)
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots


class IdentityDriftQueueProjectIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

        self.first = self._create_assessment("First", status="pending")
        self.second = self._create_assessment("Second", status="pending")
        self.first_completed = self._create_assessment("First Completed", status="passed")
        self.second_completed = self._create_assessment("Second Completed", status="blocked")

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_assessment(self, marker: str, status: str):
        project = projects.create_project({
            "name": f"{marker} Production",
            "description": "",
            "visual_style": "",
            "rules": "",
        })
        scene = scenes.create_scene({
            "project_id": project["id"],
            "scene_number": 1,
            "title": f"{marker} Scene",
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
            "title": f"{marker} Shot",
            "status": "טיוטת תמונה",
        })
        assessment = {
            "status": status,
            "passed": status == "passed",
            "attempt": 1 if status != "pending" else 0,
        }
        if status != "pending":
            assessment.update({
                "worker_id": "test-worker",
                "completed_at": "2026-07-30T06:00:00+00:00",
                "reasons": [] if status == "passed" else ["Identity mismatch."],
            })
        media = shots.create_media_result(shot["id"], {
            "media_type": "image",
            "url": f"https://example.com/{marker.lower().replace(' ', '-')}.png",
            "metadata": {"identity_drift": assessment},
        })
        return {"project": project, "scene": scene, "shot": shot, "media": media}

    def test_pending_queue_requires_project_scope_and_excludes_other_productions(self):
        result = list_pending_identity_drift(
            project_id=self.first["project"]["id"],
            limit=50,
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["media_id"], self.first["media"]["id"])
        self.assertNotEqual(result["items"][0]["media_id"], self.second["media"]["id"])

    def test_pending_queue_rejects_unknown_project(self):
        with self.assertRaises(HTTPException) as raised:
            list_pending_identity_drift(project_id=999999, limit=50)

        self.assertEqual(raised.exception.status_code, 404)

    def test_completed_queue_requires_project_scope_and_excludes_other_productions(self):
        result = list_completed_identity_drift(
            project_id=self.first_completed["project"]["id"],
            limit=50,
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["items"][0]["media_id"],
            self.first_completed["media"]["id"],
        )
        self.assertNotEqual(
            result["items"][0]["media_id"],
            self.second_completed["media"]["id"],
        )

    def test_completed_queue_rejects_unknown_project(self):
        with self.assertRaises(HTTPException) as raised:
            list_completed_identity_drift(project_id=999999, limit=50)

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
