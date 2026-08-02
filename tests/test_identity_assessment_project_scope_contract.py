import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api.identity_assessments import (
    IdentityDriftAssessmentRequest,
    IdentityDriftClaimRequest,
    claim_identity_drift,
    list_pending_identity_drift,
    record_identity_drift,
)
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots


class IdentityAssessmentProjectScopeContractTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_pending_media(self, project_name: str):
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
            "status": "תמונת טיוטה",
        })
        media = shots.create_media_result(shot["id"], {
            "media_type": "image",
            "url": f"https://example.com/{project_name}.jpg",
            "status": "טיוטה",
            "metadata": {
                "identity_drift": {
                    "status": "pending",
                    "passed": False,
                    "reasons": ["Assessment has not run yet."],
                },
            },
        })
        return project, shot, media

    def test_pending_queue_is_strictly_project_scoped(self):
        project_a, shot_a, media_a = self._create_pending_media("Project A")
        project_b, shot_b, media_b = self._create_pending_media("Project B")

        queue_a = list_pending_identity_drift(project_id=project_a["id"], limit=50)
        queue_b = list_pending_identity_drift(project_id=project_b["id"], limit=50)

        self.assertEqual(queue_a["count"], 1)
        self.assertEqual(queue_a["items"][0]["shot_id"], shot_a["id"])
        self.assertEqual(queue_a["items"][0]["media_id"], media_a["id"])
        self.assertNotEqual(queue_a["items"][0]["media_id"], media_b["id"])

        self.assertEqual(queue_b["count"], 1)
        self.assertEqual(queue_b["items"][0]["shot_id"], shot_b["id"])
        self.assertEqual(queue_b["items"][0]["media_id"], media_b["id"])
        self.assertNotEqual(queue_b["items"][0]["media_id"], media_a["id"])

    def test_completion_requires_the_claiming_worker(self):
        _, shot, media = self._create_pending_media("Worker Ownership")
        claim_identity_drift(
            shot["id"],
            media["id"],
            IdentityDriftClaimRequest(worker_id="identity-worker-1"),
        )

        with self.assertRaises(HTTPException) as context:
            record_identity_drift(
                shot["id"],
                media["id"],
                IdentityDriftAssessmentRequest(
                    worker_id="identity-worker-2",
                    status="passed",
                    passed=True,
                    score=0.95,
                ),
            )

        self.assertEqual(context.exception.status_code, 409)

        result = record_identity_drift(
            shot["id"],
            media["id"],
            IdentityDriftAssessmentRequest(
                worker_id="identity-worker-1",
                status="passed",
                passed=True,
                score=0.95,
            ),
        )
        assessment = result["media"]["metadata"]["identity_drift"]
        self.assertEqual(assessment["status"], "passed")
        self.assertTrue(assessment["passed"])
        self.assertEqual(assessment["worker_id"], "identity-worker-1")


if __name__ == "__main__":
    unittest.main()
