import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import jobs, projects, scenes, shots


class MediaJobQueueTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Queue Test",
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
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def test_idempotent_enqueue_returns_existing_active_job(self):
        first, created = jobs.enqueue_job(
            self.project_id, self.shot["id"], "image", {"prompt": "x"}, "shot-1-image-v1"
        )
        second, created_again = jobs.enqueue_job(
            self.project_id, self.shot["id"], "image", {"prompt": "x"}, "shot-1-image-v1"
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], second["id"])

    def test_claim_fail_retry_and_complete(self):
        queued, _ = jobs.enqueue_job(
            self.project_id, self.shot["id"], "video", {}, "shot-1-video-v1", max_attempts=2
        )
        claimed = jobs.claim_next_job("worker-a")
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["attempts"], 1)

        retry = jobs.fail_job(queued["id"], "temporary", retryable=True)
        self.assertEqual(retry["status"], "retrying")

        claimed_again = jobs.claim_next_job("worker-b")
        self.assertEqual(claimed_again["attempts"], 2)
        done = jobs.complete_job(queued["id"], {"url": "https://example.com/video.mp4"})
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"]["url"], "https://example.com/video.mp4")

    def test_retry_budget_ends_in_failure(self):
        queued, _ = jobs.enqueue_job(
            self.project_id, self.shot["id"], "image", {}, "shot-1-image-v2", max_attempts=1
        )
        jobs.claim_next_job("worker")
        failed = jobs.fail_job(queued["id"], "permanent", retryable=True)
        self.assertEqual(failed["status"], "failed")

    def test_failed_job_can_be_requeued_with_same_idempotency_key(self):
        queued, _ = jobs.enqueue_job(
            self.project_id, self.shot["id"], "image", {"prompt": "first"}, "shot-1-image-v3", max_attempts=1
        )
        jobs.claim_next_job("worker")
        jobs.fail_job(queued["id"], "provider outage", retryable=True)

        requeued, created = jobs.enqueue_job(
            self.project_id, self.shot["id"], "image", {"prompt": "second"}, "shot-1-image-v3", max_attempts=2
        )

        self.assertTrue(created)
        self.assertEqual(requeued["id"], queued["id"])
        self.assertEqual(requeued["status"], "queued")
        self.assertEqual(requeued["attempts"], 0)
        self.assertEqual(requeued["max_attempts"], 2)
        self.assertEqual(requeued["payload"]["prompt"], "second")
        self.assertEqual(requeued["last_error"], "")

    def test_enqueue_rejects_invalid_retry_budget(self):
        with self.assertRaises(ValueError):
            jobs.enqueue_job(
                self.project_id, self.shot["id"], "image", {}, "shot-1-invalid", max_attempts=0
            )

    def test_cost_tracking_and_project_summary(self):
        first, _ = jobs.enqueue_job(
            self.project_id, self.shot["id"], "image", {}, "shot-1-cost-image", estimated_cost_usd=0.08
        )
        second, _ = jobs.enqueue_job(
            self.project_id, self.shot["id"], "video", {}, "shot-1-cost-video", estimated_cost_usd=1.25
        )
        jobs.complete_job(first["id"], {"url": "image.png"}, actual_cost_usd=0.07)
        jobs.complete_job(second["id"], {"url": "video.mp4"}, actual_cost_usd=1.10)

        summary = jobs.get_cost_summary(self.project_id)
        self.assertEqual(summary["job_count"], 2)
        self.assertAlmostEqual(summary["estimated_cost_usd"], 1.33)
        self.assertAlmostEqual(summary["actual_cost_usd"], 1.17)

    def test_negative_costs_are_rejected(self):
        with self.assertRaises(ValueError):
            jobs.enqueue_job(
                self.project_id, self.shot["id"], "image", {}, "shot-negative-cost", estimated_cost_usd=-0.01
            )
        queued, _ = jobs.enqueue_job(
            self.project_id, self.shot["id"], "image", {}, "shot-complete-negative"
        )
        with self.assertRaises(ValueError):
            jobs.complete_job(queued["id"], {}, actual_cost_usd=-0.01)


if __name__ == "__main__":
    unittest.main()
