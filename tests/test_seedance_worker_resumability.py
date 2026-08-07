"""Gate: Seedance video worker resumability.

Before this fix, SeedanceProvider only exposed a blocking generate() that
submitted to fal.ai and waited for completion in one call. A crash or
retryable failure mid-poll had no persisted request id to resume, so a retry
or worker restart called generate() again — a second, separately billed
fal.ai submission for the same shot. These tests prove that gap is closed by
routing Seedance through the same submit()/check_task() resumable contract
already proven for Kling.

The fal.ai network boundary is faked; no live or paid provider call is made.
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from app.database.connection import get_connection, init_db
from app.repositories import jobs, projects, scenes, shots
from app.repositories.approvals import APPROVED
from app.services.seedance_provider import SeedanceProvider
from app.services.video_provider import VideoGenerationRequest
import app.worker as worker


class _FakeSeedance(SeedanceProvider):
    """A SeedanceProvider whose network calls are scripted and counted.

    Subclassing the real provider keeps the worker's duck-typed dispatch
    (submit()/check_task()/model_for()/cost_for()) honest while the actual
    fal.ai calls stay offline.
    """

    def __init__(self, statuses, task_id="bytedance/seedance-2.0/image-to-video::fake-req-1"):
        self.task_id = task_id
        self.submit_calls = 0
        self.check_calls = 0
        self._statuses = list(statuses)

    def submit(self, request):  # noqa: D401 - test double
        self.submit_calls += 1
        return self.task_id

    def check_task(self, task_id):  # noqa: D401 - test double
        self.check_calls += 1
        assert task_id == self.task_id, "resumed against a different task id"
        outcome = self._statuses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def model_for(self, request):
        return "bytedance/seedance-2.0/image-to-video"

    def cost_for(self, request):
        return 1.517


_SUCCEED = {"status": "succeed", "url": "https://cdn.fal.example/final.mp4", "reason": ""}
_AUTH_FAILED = {"status": "failed", "url": "", "reason": "authentication_failed"}


class SeedanceWorkerResumabilityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project(
            {"name": "SeedanceGate", "description": "", "visual_style": "", "rules": ""}
        )
        scene = scenes.create_scene(
            {
                "project_id": project["id"],
                "scene_number": 1,
                "title": "S",
                "status": "מתוכנן",
                "story_goal": "",
                "emotion": "",
                "conflict": "",
                "beginning": "",
                "ending": "",
                "notes": "",
            }
        )
        self.project_id = project["id"]
        self.shot = shots.create_shot(
            {
                "project_id": project["id"],
                "scene_id": scene["id"],
                "shot_number": 1,
                "title": "Shot",
                "prompt": "a wide establishing shot",
                "duration_seconds": 5,
            }
        )
        shots.create_media_result(
            self.shot["id"],
            {
                "media_type": "image",
                "url": "https://cdn.example/approved.png",
                "status": APPROVED,
            },
        )
        self._real_sleep = worker.time.sleep
        worker.time.sleep = lambda *_a, **_k: None
        self._real_get_provider = worker.get_video_provider

    def tearDown(self):
        worker.time.sleep = self._real_sleep
        worker.get_video_provider = self._real_get_provider
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _enqueue_video(self, key="shot-1-video-v1", max_attempts=3):
        job, _ = jobs.enqueue_job(
            self.project_id, self.shot["id"], "video", {}, key, max_attempts=max_attempts
        )
        return job

    def _use_provider(self, fake):
        worker.get_video_provider = lambda: fake

    def test_submit_or_resume_submits_once_then_resumes(self):
        fake = _FakeSeedance([])
        request = VideoGenerationRequest(
            image_url="https://cdn.example/approved.png", prompt="p", duration_seconds=5
        )
        self._enqueue_video()
        claimed = jobs.claim_next_job("w1")
        first = worker._submit_or_resume_task(fake, request, claimed)
        self.assertEqual(first, fake.task_id)
        self.assertEqual(fake.submit_calls, 1)

        resumed_job = jobs.get_job(claimed["id"])
        second = worker._submit_or_resume_task(fake, request, resumed_job)
        self.assertEqual(second, fake.task_id)
        self.assertEqual(fake.submit_calls, 1)

    def test_video_job_completes_stores_result_and_updates_shot(self):
        fake = _FakeSeedance([_SUCCEED])
        self._use_provider(fake)
        job = self._enqueue_video()

        done = worker.process_one_job("w1")

        self.assertEqual(done["status"], "completed")
        self.assertEqual(fake.submit_calls, 1)
        videos = [
            m for m in shots.list_media_results(self.shot["id"]) if m["media_type"] == "video"
        ]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["url"], _SUCCEED["url"])
        self.assertEqual(videos[0]["provider"], "seedance")
        self.assertEqual(shots.get_shot(self.shot["id"])["status"], "וידאו טיוטה")
        self.assertEqual(jobs.get_job(job["id"])["provider_task_id"], fake.task_id)

    def test_completed_job_is_never_reclaimed_or_reprocessed(self):
        fake = _FakeSeedance([_SUCCEED])
        self._use_provider(fake)
        job = self._enqueue_video()

        done = worker.process_one_job("w1")
        self.assertEqual(done["status"], "completed")

        # A completed job must not be picked up again by claim_next_job,
        # and staleness reclaim must not touch it either — it isn't 'running'.
        self.assertIsNone(jobs.claim_next_job("w2"))
        reclaimed = jobs.reclaim_stale_jobs(stale_after_seconds=0)
        self.assertNotIn(job["id"], reclaimed)
        self.assertEqual(jobs.get_job(job["id"])["status"], "completed")
        self.assertEqual(fake.submit_calls, 1)

    def test_retryable_poll_failure_does_not_resubmit_on_retry(self):
        fake = _FakeSeedance([TimeoutError("slow"), _SUCCEED])
        self._use_provider(fake)
        job = self._enqueue_video(max_attempts=3)

        first = worker.process_one_job("w1")
        self.assertEqual(first["status"], "retrying")
        self.assertEqual(fake.submit_calls, 1)
        self.assertEqual(jobs.get_job(job["id"])["provider_task_id"], fake.task_id)

        second = worker.process_one_job("w1")
        self.assertEqual(second["status"], "completed")
        # This is the core regression check: exactly one submission across
        # the whole retry sequence, never a second paid fal.ai request.
        self.assertEqual(fake.submit_calls, 1)

    def test_authentication_failure_is_not_retried(self):
        fake = _FakeSeedance([_AUTH_FAILED])
        self._use_provider(fake)
        self._enqueue_video(max_attempts=3)

        done = worker.process_one_job("w1")

        self.assertEqual(done["status"], "failed")
        self.assertIn("authentication_failed", done["last_error"])
        self.assertEqual(fake.submit_calls, 1)

    def _age_job(self, job_id, seconds):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=seconds)
        ).strftime("%Y-%m-%d %H:%M:%S")
        with _closing_conn() as conn:
            conn.execute("UPDATE media_jobs SET updated_at=? WHERE id=?", (cutoff, job_id))
            conn.commit()

    def test_worker_restart_resumes_persisted_task_without_resubmitting(self):
        # Simulate a worker that submitted, persisted the task id, then died
        # mid-poll (the exact bug this fix closes): the job is left 'running'
        # and stale, and the fake provider refuses a second submit by
        # asserting submit_calls stays at 0 across the whole restart+resume.
        self._enqueue_video()
        claimed = jobs.claim_next_job("w1")
        task_id = "bytedance/seedance-2.0/image-to-video::already-submitted-req"
        jobs.record_provider_task_id(claimed["id"], task_id)
        self._age_job(claimed["id"], jobs.STALE_RUNNING_SECONDS + 60)

        fake = _FakeSeedance([_SUCCEED], task_id=task_id)
        self._use_provider(fake)
        jobs.reclaim_stale_jobs()

        done = worker.process_one_job("w2")
        self.assertEqual(done["status"], "completed")
        self.assertEqual(fake.submit_calls, 0)
        self.assertEqual(fake.check_calls, 1)
        videos = [
            m for m in shots.list_media_results(self.shot["id"]) if m["media_type"] == "video"
        ]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["url"], _SUCCEED["url"])


def _closing_conn():
    from contextlib import closing

    return closing(get_connection())


if __name__ == "__main__":
    unittest.main()
