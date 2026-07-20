import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.identity_assessments import (
    IdentityDriftAssessmentRequest,
    IdentityDriftClaimRequest,
    IdentityDriftEvaluationRequest,
    claim_identity_drift,
    evaluate_and_record_identity_drift,
    list_pending_identity_drift,
    record_identity_drift,
    requeue_stale_identity_drift,
)
from app.core.config import settings
from app.database.connection import get_connection, init_db
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

    def _set_claimed_at(self, media_id: int, claimed_at: datetime):
        with closing(get_connection()) as conn:
            row = conn.execute(
                "SELECT metadata_json FROM media_results WHERE id=?",
                (media_id,),
            ).fetchone()
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata["identity_drift"]["claimed_at"] = claimed_at.isoformat()
            conn.execute(
                "UPDATE media_results SET metadata_json=? WHERE id=?",
                (json.dumps(metadata), media_id),
            )
            conn.commit()

    def test_lists_only_pending_image_assessments(self):
        completed = shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/completed.jpg",
            "status": "טיוטה",
            "metadata": {
                "identity_drift": {"status": "passed", "passed": True},
            },
        })
        shots.create_media_result(self.shot["id"], {
            "media_type": "video",
            "url": "https://example.com/video.mp4",
            "status": "טיוטה",
            "metadata": {
                "identity_drift": {"status": "pending", "passed": False},
            },
        })

        result = list_pending_identity_drift(limit=50)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["media_id"], self.media["id"])
        self.assertEqual(result["items"][0]["shot_id"], self.shot["id"])
        self.assertNotEqual(result["items"][0]["media_id"], completed["id"])

    def test_pending_assessment_queue_respects_limit(self):
        second = shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/generated-2.jpg",
            "status": "טיוטה",
            "metadata": {
                "identity_drift": {"status": "pending", "passed": False},
            },
        })

        result = list_pending_identity_drift(limit=1)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["media_id"], self.media["id"])
        self.assertNotEqual(result["items"][0]["media_id"], second["id"])

    def test_claim_marks_pending_assessment_running(self):
        result = claim_identity_drift(
            self.shot["id"],
            self.media["id"],
            IdentityDriftClaimRequest(worker_id="identity-worker-1"),
        )

        assessment = result["identity_drift"]
        self.assertEqual(assessment["status"], "running")
        self.assertFalse(assessment["passed"])
        self.assertEqual(assessment["worker_id"], "identity-worker-1")
        self.assertEqual(assessment["attempt"], 1)
        self.assertTrue(assessment["claimed_at"].endswith("+00:00"))
        self.assertEqual(list_pending_identity_drift(limit=50)["count"], 0)

    def test_claim_rejects_duplicate_worker_pickup(self):
        request = IdentityDriftClaimRequest(worker_id="identity-worker-1")
        claim_identity_drift(self.shot["id"], self.media["id"], request)

        with self.assertRaises(HTTPException) as context:
            claim_identity_drift(self.shot["id"], self.media["id"], request)

        self.assertEqual(context.exception.status_code, 409)

    def test_requeues_only_expired_running_assessments(self):
        claim_identity_drift(
            self.shot["id"],
            self.media["id"],
            IdentityDriftClaimRequest(worker_id="stale-worker"),
        )
        self._set_claimed_at(
            self.media["id"],
            datetime.now(timezone.utc) - timedelta(minutes=45),
        )
        recent = shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/recent.jpg",
            "status": "טיוטה",
            "metadata": {
                "identity_drift": {
                    "status": "running",
                    "passed": False,
                    "worker_id": "recent-worker",
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                    "attempt": 1,
                },
            },
        })

        result = requeue_stale_identity_drift(max_age_minutes=30, limit=50)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["media_id"], self.media["id"])
        pending = list_pending_identity_drift(limit=50)
        self.assertEqual(pending["count"], 1)
        assessment = pending["items"][0]["identity_drift"]
        self.assertEqual(assessment["status"], "pending")
        self.assertEqual(assessment["attempt"], 1)
        self.assertNotIn("worker_id", assessment)
        self.assertNotIn("claimed_at", assessment)
        self.assertNotEqual(result["items"][0]["media_id"], recent["id"])

    def test_requeue_respects_limit(self):
        claim_identity_drift(
            self.shot["id"],
            self.media["id"],
            IdentityDriftClaimRequest(worker_id="worker-1"),
        )
        self._set_claimed_at(
            self.media["id"],
            datetime.now(timezone.utc) - timedelta(minutes=60),
        )
        second = shots.create_media_result(self.shot["id"], {
            "media_type": "image",
            "url": "https://example.com/stale-2.jpg",
            "status": "טיוטה",
            "metadata": {
                "identity_drift": {
                    "status": "running",
                    "passed": False,
                    "worker_id": "worker-2",
                    "claimed_at": (
                        datetime.now(timezone.utc) - timedelta(minutes=60)
                    ).isoformat(),
                    "attempt": 1,
                },
            },
        })

        result = requeue_stale_identity_drift(max_age_minutes=30, limit=1)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["media_id"], self.media["id"])
        self.assertNotEqual(result["items"][0]["media_id"], second["id"])

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

    def test_evaluates_and_records_normalized_provider_output(self):
        result = evaluate_and_record_identity_drift(
            self.shot["id"],
            self.media["id"],
            IdentityDriftEvaluationRequest(
                identity_similarity=0.91,
                flags=["lighting_changed", "lighting_changed"],
                evidence={"reference_media_id": 7},
                provider="vision-adapter",
                model="identity-v2",
            ),
        )

        assessment = result["media"]["metadata"]["identity_drift"]
        self.assertEqual(assessment["status"], "passed")
        self.assertTrue(assessment["passed"])
        self.assertEqual(assessment["identity_similarity"], 0.91)
        self.assertEqual(assessment["flags"], ["lighting_changed"])
        self.assertEqual(assessment["evidence"]["reference_media_id"], 7)
        self.assertEqual(assessment["provider"], "vision-adapter")
        self.assertEqual(assessment["model"], "identity-v2")

    def test_evaluation_blocks_critical_identity_flag(self):
        result = evaluate_and_record_identity_drift(
            self.shot["id"],
            self.media["id"],
            IdentityDriftEvaluationRequest(
                identity_similarity=0.99,
                flags=["different_person"],
            ),
        )

        assessment = result["media"]["metadata"]["identity_drift"]
        self.assertEqual(assessment["status"], "blocked")
        self.assertFalse(assessment["passed"])
        self.assertEqual(assessment["blocking_flags"], ["different_person"])

    def test_rejects_inconsistent_passed_outcome(self):
        with self.assertRaises(ValidationError):
            IdentityDriftAssessmentRequest(status="passed", passed=False)


if __name__ == "__main__":
    unittest.main()
