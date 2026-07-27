import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.video_generation import get_video_job_status


class VideoJobStatusTests(unittest.TestCase):
    def test_returns_provider_neutral_running_status(self):
        job = {
            "id": 11,
            "shot_id": 7,
            "job_type": "video",
            "status": "running",
            "attempts": 1,
            "max_attempts": 3,
            "updated_at": "2026-07-27 07:00:00",
            "finished_at": None,
            "payload": {"provider_secret": "must-not-leak"},
            "last_error": "raw provider details",
        }
        with patch("app.api.video_generation.jobs.get_job", return_value=job):
            result = get_video_job_status(11)

        self.assertEqual(result["status"], "running")
        self.assertFalse(result["terminal"])
        self.assertTrue(result["retryable"])
        self.assertEqual(result["attempts_remaining"], 2)
        self.assertNotIn("payload", result)
        self.assertNotIn("last_error", result)

    def test_completed_status_is_terminal_and_not_retryable(self):
        job = {
            "id": 12,
            "shot_id": 8,
            "job_type": "video",
            "status": "completed",
            "attempts": 1,
            "max_attempts": 3,
            "updated_at": "2026-07-27 07:05:00",
            "finished_at": "2026-07-27 07:05:00",
        }
        with patch("app.api.video_generation.jobs.get_job", return_value=job):
            result = get_video_job_status(12)

        self.assertTrue(result["terminal"])
        self.assertFalse(result["retryable"])
        self.assertEqual(result["attempts_remaining"], 2)

    def test_missing_job_returns_404(self):
        with patch("app.api.video_generation.jobs.get_job", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                get_video_job_status(999)
        self.assertEqual(raised.exception.status_code, 404)

    def test_non_video_job_returns_409(self):
        with patch(
            "app.api.video_generation.jobs.get_job",
            return_value={"id": 13, "job_type": "image"},
        ):
            with self.assertRaises(HTTPException) as raised:
                get_video_job_status(13)
        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
