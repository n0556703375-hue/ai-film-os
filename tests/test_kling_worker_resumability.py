"""Gate 2 resumability contract for the Kling video worker.

These tests prove the two properties the Milestone B Gate 2 checklist calls
out that a naive submit-then-block worker cannot satisfy:

  * No duplicate submission on retry — a retryable failure mid-poll must not
    submit a second (separately billed) Kling task.
  * Worker resumes correctly after restart — a job orphaned in 'running' by a
    crash/redeploy is reclaimed and finished against the *same* provider task.

The Kling network boundary is faked; no live or paid provider call is made.
"""

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from app.database.connection import get_connection, init_db
from app.repositories import jobs, projects, scenes, shots
from app.repositories.approvals import APPROVED
from app.services.kling_provider import KlingProvider
from app.services.video_provider import VideoGenerationRequest
import app.worker as worker


class _FakeKling(KlingProvider):
    """A KlingProvider whose network calls are scripted and counted.

    Subclassing the real provider keeps the worker's ``isinstance`` branch
    honest while ``submit``/``check_task`` stay offline.
    """

    def __init__(self, statuses, task_id="kling-task-abc123"):
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


_SUCCEED = {"status": "succeed", "url": "https://cdn.kling.example/final.mp4", "reason": ""}


class KlingWorkerResumabilityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project(
            {"name": "Gate2", "description": "", "visual_style": "", "rules": ""}
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
        # Video generation requires an approved source image.
        shots.create_media_result(
            self.shot["id"],
            {
                "media_type": "image",
                "url": "https://cdn.example/approved.png",
                "status": APPROVED,
            },
        )
        # Keep polling instantaneous — the provider is faked.
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

    # --- persistence primitive -------------------------------------------

    def test_record_provider_task_id_persists_without_changing_status(self):
        job = self._enqueue_video()
        claimed = jobs.claim_next_job("w1")
        updated = jobs.record_provider_task_id(claimed["id"], "kling-xyz")
        self.assertEqual(updated["provider_task_id"], "kling-xyz")
        self.assertEqual(updated["status"], "running")
        # Survives a fresh read.
        self.assertEqual(jobs.get_job(job["id"])["provider_task_id"], "kling-xyz")

    def test_record_provider_task_id_rejects_empty(self):
        job = self._enqueue_video()
        with self.assertRaises(ValueError):
            jobs.record_provider_task_id(job["id"], "  ")

    # --- submit-at-most-once ---------------------------------------------

    def test_submit_or_resume_submits_once_then_resumes(self):
        fake = _FakeKling([])
        request = VideoGenerationRequest(
            image_url="https://cdn.example/approved.png",
            prompt="p",
            duration_seconds=5,
        )
        self._enqueue_video()
        claimed = jobs.claim_next_job("w1")
        first = worker._submit_or_resume_kling(fake, request, claimed)
        self.assertEqual(first, fake.task_id)
        self.assertEqual(fake.submit_calls, 1)

        # A re-claimed job now carries the persisted task id: no second submit.
        resumed_job = jobs.get_job(claimed["id"])
        second = worker._submit_or_resume_kling(fake, request, resumed_job)
        self.assertEqual(second, fake.task_id)
        self.assertEqual(fake.submit_calls, 1)

    # --- happy path -------------------------------------------------------

    def test_video_job_completes_stores_result_and_updates_shot(self):
        fake = _FakeKling([_SUCCEED])
        self._use_provider(fake)
        job = self._enqueue_video()

        done = worker.process_one_job("w1")

        self.assertEqual(done["status"], "completed")
        self.assertEqual(fake.submit_calls, 1)
        # Result URL stored in media_results.
        videos = [
            m for m in shots.list_media_results(self.shot["id"])
            if m["media_type"] == "video"
        ]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["url"], _SUCCEED["url"])
        self.assertEqual(videos[0]["provider"], "kling")
        # Shot status advanced.
        self.assertEqual(shots.get_shot(self.shot["id"])["status"], "וידאו טיוטה")
        # Task id persisted on the job.
        self.assertEqual(jobs.get_job(job["id"])["provider_task_id"], fake.task_id)

    # --- no duplicate submission on retry --------------------------------

    def test_retryable_poll_failure_does_not_resubmit_on_retry(self):
        # First poll raises a retryable timeout after the task was submitted;
        # the second attempt must resume the same task, not submit a new one.
        fake = _FakeKling([TimeoutError("slow"), _SUCCEED])
        self._use_provider(fake)
        job = self._enqueue_video(max_attempts=3)

        first = worker.process_one_job("w1")
        self.assertEqual(first["status"], "retrying")
        self.assertEqual(fake.submit_calls, 1)
        self.assertEqual(jobs.get_job(job["id"])["provider_task_id"], fake.task_id)

        second = worker.process_one_job("w1")
        self.assertEqual(second["status"], "completed")
        # Still exactly one submission across the whole retry sequence.
        self.assertEqual(fake.submit_calls, 1)
        videos = [
            m for m in shots.list_media_results(self.shot["id"])
            if m["media_type"] == "video"
        ]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["url"], _SUCCEED["url"])

    # --- stale-job reclaim (worker restart) ------------------------------

    def _age_job(self, job_id, seconds):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=seconds)
        ).strftime("%Y-%m-%d %H:%M:%S")
        with closing_conn() as conn:
            conn.execute(
                "UPDATE media_jobs SET updated_at=? WHERE id=?", (cutoff, job_id)
            )
            conn.commit()

    def test_reclaim_requeues_stale_running_job(self):
        self._enqueue_video()
        claimed = jobs.claim_next_job("w1")
        self.assertEqual(claimed["status"], "running")
        self._age_job(claimed["id"], jobs.STALE_RUNNING_SECONDS + 60)

        reclaimed = jobs.reclaim_stale_jobs()
        self.assertIn(claimed["id"], reclaimed)
        self.assertEqual(jobs.get_job(claimed["id"])["status"], "retrying")

    def test_reclaim_ignores_fresh_running_job(self):
        self._enqueue_video()
        claimed = jobs.claim_next_job("w1")
        reclaimed = jobs.reclaim_stale_jobs()
        self.assertNotIn(claimed["id"], reclaimed)
        self.assertEqual(jobs.get_job(claimed["id"])["status"], "running")

    def test_reclaim_marks_exhausted_job_failed(self):
        self._enqueue_video(max_attempts=1)
        claimed = jobs.claim_next_job("w1")  # attempts -> 1 == max_attempts
        self._age_job(claimed["id"], jobs.STALE_RUNNING_SECONDS + 60)
        jobs.reclaim_stale_jobs()
        self.assertEqual(jobs.get_job(claimed["id"])["status"], "failed")

    def test_worker_restart_resumes_persisted_task_without_resubmitting(self):
        # Simulate a worker that submitted, persisted the task id, then died
        # mid-poll: the job is left 'running' and stale, and the fake provider
        # will refuse a second submit by asserting submit is never called.
        self._enqueue_video()
        claimed = jobs.claim_next_job("w1")
        jobs.record_provider_task_id(claimed["id"], "kling-task-abc123")
        self._age_job(claimed["id"], jobs.STALE_RUNNING_SECONDS + 60)

        # Fresh worker starts: reclaim, then process. submit must NOT run.
        fake = _FakeKling([_SUCCEED])
        self._use_provider(fake)
        jobs.reclaim_stale_jobs()

        done = worker.process_one_job("w2")
        self.assertEqual(done["status"], "completed")
        self.assertEqual(fake.submit_calls, 0)
        self.assertEqual(fake.check_calls, 1)
        videos = [
            m for m in shots.list_media_results(self.shot["id"])
            if m["media_type"] == "video"
        ]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["url"], _SUCCEED["url"])


def closing_conn():
    from contextlib import closing

    return closing(get_connection())


if __name__ == "__main__":
    unittest.main()
