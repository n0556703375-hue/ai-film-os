import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.api.identity_assessments import (
    IdentityDriftAssessmentRequest,
    record_identity_drift,
)
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots


class IdentityDriftAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Identity Assessment Test",
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
            "status": "תמונת טיוטה",
        })
        self.media = shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/generated.jpg",
            "status": "טיוטה",
            "metadata": {
                "magnific_task_id": "task-identity-1",
                "identity_drift": {
                    "status": "pending",
                    "passed": False,
                    "reasons": ["Assessment has not run yet."],
                },
            },
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def test_records_passed_assessment_without_losing_provider_metadata(self):
        result = record_identity_drift(
            self.shot["id"],
            self.media["id"],
            IdentityDriftAssessmentRequest(
                status="passed",
                passed=True,
                score=0.94,
                reasons=[],
                provider="internal",
                model="identity-v1",
            ),
        )

        metadata = result["media"]["metadata"]
        self.assertEqual(metadata["magnific_task_id"], "task-identity-1")
        self.assertEqual(metadata["identity_drift"]["status"], "passed")
        self.assertTrue(metadata["identity_drift"]["passed"])
        self.assertEqual(metadata["identity_drift"]["score"], 0.94)

    def test_rejects_inconsistent_passed_outcome(self):
        with self.assertRaises(ValidationError):
            IdentityDriftAssessmentRequest(status="passed", passed=False)


if __name__ == "__main__":
    unittest.main()
