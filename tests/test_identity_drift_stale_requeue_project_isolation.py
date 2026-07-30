import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from app.api.identity_assessments import requeue_stale_identity_drift
from app.core.config import settings
from app.database.connection import get_connection, init_db
from app.repositories import projects, scenes, shots


class IdentityDriftStaleRequeueProjectIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

        self.first = self._create_stale_running_assessment("First")
        self.second = self._create_stale_running_assessment("Second")

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_stale_running_assessment(self, marker: str):
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
        claimed_at = datetime.now(timezone.utc) - timedelta(hours=2)
        media = shots.create_media_result(shot["id"], {
            "media_type": "image",
            "url": f"https://example.com/{marker.lower()}.png",
            "metadata": {
                "identity_drift": {
                    "status": "running",
                    "passed": False,
                    "worker_id": f"{marker.lower()}-worker",
                    "claimed_at": claimed_at.isoformat(),
                    "attempt": 1,
                }
            },
        })
        return {"project": project, "scene": scene, "shot": shot, "media": media}

    def _identity_drift_status(self, media_id: int) -> str:
        with closing(get_connection()) as conn:
            row = conn.execute(
                "SELECT metadata_json FROM media_results WHERE id=?",
                (media_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        metadata = json.loads(row["metadata_json"] or "{}")
        return metadata["identity_drift"]["status"]

    def test_requeue_requires_project_scope_and_does_not_mutate_other_productions(self):
        result = requeue_stale_identity_drift(
            project_id=self.first["project"]["id"],
            max_age_minutes=30,
            limit=50,
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["media_id"], self.first["media"]["id"])
        self.assertNotEqual(result["items"][0]["media_id"], self.second["media"]["id"])
        self.assertEqual(
            self._identity_drift_status(self.second["media"]["id"]),
            "running",
        )

    def test_requeue_rejects_unknown_project_without_mutation(self):
        with self.assertRaises(HTTPException) as raised:
            requeue_stale_identity_drift(
                project_id=999999,
                max_age_minutes=30,
                limit=50,
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            self._identity_drift_status(self.first["media"]["id"]),
            "running",
        )
        self.assertEqual(
            self._identity_drift_status(self.second["media"]["id"]),
            "running",
        )


if __name__ == "__main__":
    unittest.main()
