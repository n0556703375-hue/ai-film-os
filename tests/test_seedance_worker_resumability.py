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
from unittest.mock import patch

from app.core.config import settings
from app.database.connection import get_connection, init_db
from app.repositories import jobs, projects, scenes, shots
from app.repositories.approvals import APPROVED
from app.services.seedance_provider import SeedanceProvider
from app.services.video_persistence import VideoPersistenceError
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

        # persist_remote_video() makes a real network call to download the
        # provider's video; these tests exercise worker orchestration, not
        # that download itself (covered in isolation by
        # tests/test_video_persistence.py), so it defaults to a stand-in
        # success. Tests that care about persistence behavior override this.
        self.persisted_url = f"/generated/videos/shot-{self.shot['id']}/mocked-uuid.mp4"
        self.persist_calls = []

        def _fake_persist(provider_video_url, shot_id, **kwargs):
            self.persist_calls.append((provider_video_url, shot_id))
            return {"url": self.persisted_url, "size_bytes": 1024, "content_type": "video/mp4"}

        persist_patcher = patch("app.worker.persist_remote_video", side_effect=_fake_persist)
        self.mock_persist = persist_patcher.start()
        self.addCleanup(persist_patcher.stop)

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
        worker.get_video_provider = lambda **kwargs: fake

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
        # The persisted AI Film OS URL is stored, never the provider's — the
        # browser must not depend on the external fal.ai video URL.
        self.assertEqual(videos[0]["url"], self.persisted_url)
        self.assertNotEqual(videos[0]["url"], _SUCCEED["url"])
        self.assertEqual(videos[0]["provider"], "seedance")
        self.assertEqual(shots.get_shot(self.shot["id"])["status"], "וידאו טיוטה")
        self.assertEqual(jobs.get_job(job["id"])["provider_task_id"], fake.task_id)
        # persist_remote_video() must receive the provider's own video URL.
        self.assertEqual(self.persist_calls, [(_SUCCEED["url"], self.shot["id"])])

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
        self.assertEqual(videos[0]["url"], self.persisted_url)

    # --- video persistence integration (item 11-14 of the persistence gate) ---

    def test_persistence_failure_does_not_mark_job_completed(self):
        fake = _FakeSeedance([_SUCCEED])
        self._use_provider(fake)
        self._enqueue_video()
        self.mock_persist.side_effect = VideoPersistenceError(VideoPersistenceError.UNREACHABLE)

        done = worker.process_one_job("w1")

        self.assertNotEqual(done["status"], "completed")
        self.assertEqual(done["status"], "retrying")
        self.assertIn("video_persistence_failed", done["last_error"])
        videos = [
            m for m in shots.list_media_results(self.shot["id"]) if m["media_type"] == "video"
        ]
        self.assertEqual(videos, [], "no media_result may exist until persistence succeeds")
        # The provider generation already succeeded and was paid for — the
        # failure was purely in the local download/storage step.
        self.assertEqual(fake.submit_calls, 1)

    def test_persistence_retry_does_not_create_a_second_seedance_submission(self):
        # provider completed -> persistence fails -> job retried -> resumes
        # the existing provider result -> persistence succeeds. Only the
        # download/storage step is retried; fal.ai is never re-submitted to.
        fake = _FakeSeedance([_SUCCEED, _SUCCEED])
        self._use_provider(fake)
        job = self._enqueue_video(max_attempts=3)

        self.mock_persist.side_effect = VideoPersistenceError(VideoPersistenceError.WRITE_FAILED)
        first = worker.process_one_job("w1")
        self.assertEqual(first["status"], "retrying")
        self.assertEqual(fake.submit_calls, 1)
        self.assertEqual(jobs.get_job(job["id"])["provider_task_id"], fake.task_id)

        # Second attempt: persistence now succeeds.
        self.mock_persist.side_effect = None
        self.mock_persist.return_value = {
            "url": self.persisted_url,
            "size_bytes": 1024,
            "content_type": "video/mp4",
        }
        second = worker.process_one_job("w1")

        self.assertEqual(second["status"], "completed")
        # This is the exact billing-safety invariant this fix protects: two
        # process_one_job() attempts, exactly one Seedance submission.
        self.assertEqual(fake.submit_calls, 1)
        self.assertEqual(fake.check_calls, 2)
        videos = [
            m for m in shots.list_media_results(self.shot["id"]) if m["media_type"] == "video"
        ]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["url"], self.persisted_url)

    def test_existing_provider_task_id_is_reused_across_persistence_retries(self):
        fake = _FakeSeedance([_SUCCEED, _SUCCEED, _SUCCEED])
        self._use_provider(fake)
        self._enqueue_video(max_attempts=5)

        self.mock_persist.side_effect = VideoPersistenceError(VideoPersistenceError.UNREACHABLE)
        worker.process_one_job("w1")
        worker.process_one_job("w1")
        task_id_after_two_failures = fake.task_id

        self.mock_persist.side_effect = None
        self.mock_persist.return_value = {
            "url": self.persisted_url,
            "size_bytes": 1024,
            "content_type": "video/mp4",
        }
        done = worker.process_one_job("w1")

        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["provider_task_id"], task_id_after_two_failures)
        self.assertEqual(fake.submit_calls, 1, "three attempts, still exactly one submission")

    def test_media_result_and_metadata_never_contain_the_provider_video_url(self):
        fake = _FakeSeedance([_SUCCEED])
        self._use_provider(fake)
        self._enqueue_video()

        done = worker.process_one_job("w1")

        video = next(
            m for m in shots.list_media_results(self.shot["id"]) if m["media_type"] == "video"
        )
        serialized = str(video) + str(done)
        self.assertNotIn("cdn.fal.example", serialized)
        self.assertNotIn(_SUCCEED["url"], serialized)

    def test_video_persistence_error_message_is_sanitized_and_retryable(self):
        error = VideoPersistenceError(VideoPersistenceError.PRIVATE_HOST)
        self.assertTrue(error.retryable)
        self.assertEqual(str(error), "video_persistence_failed: private_host")
        self.assertNotIn("fal.media", str(error))


def _closing_conn():
    from contextlib import closing

    return closing(get_connection())


if __name__ == "__main__":
    unittest.main()
