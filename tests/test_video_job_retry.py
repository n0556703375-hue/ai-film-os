import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.video_generation import ConfirmedRetryRequest, retry_video_job


class VideoJobRetryTests(unittest.TestCase):
    def test_retry_requires_explicit_confirmation(self):
        with self.assertRaises(ValidationError):
            ConfirmedRetryRequest(confirmed=False)

    def test_retries_failed_video_job_without_exposing_payload(self):
        failed = {
            "id": 31,
            "shot_id": 7,
            "job_type": "video",
            "status": "failed",
            "attempts": 1,
            "max_attempts": 3,
        }
        retried = {**failed, "status": "retrying", "finished_at": None}
        with patch("app.api.video_generation.jobs.get_job", return_value=failed), patch(
            "app.api.video_generation.jobs.retry_failed_job", return_value=retried
        ) as retry:
            result = retry_video_job(31, ConfirmedRetryRequest(confirmed=True))

        retry.assert_called_once_with(31)
        self.assertEqual(result["status"], "retrying")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["attempts_remaining"], 2)
        self.assertNotIn("payload", result)
        self.assertNotIn("last_error", result)

    def test_missing_job_returns_404(self):
        with patch("app.api.video_generation.jobs.get_job", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                retry_video_job(999, ConfirmedRetryRequest(confirmed=True))
        self.assertEqual(raised.exception.status_code, 404)

    def test_non_video_job_returns_409(self):
        with patch(
            "app.api.video_generation.jobs.get_job",
            return_value={"id": 32, "job_type": "image"},
        ):
            with self.assertRaises(HTTPException) as raised:
                retry_video_job(32, ConfirmedRetryRequest(confirmed=True))
        self.assertEqual(raised.exception.status_code, 409)

    def test_exhausted_retry_is_blocked(self):
        failed = {
            "id": 33,
            "shot_id": 8,
            "job_type": "video",
            "status": "failed",
            "attempts": 3,
            "max_attempts": 3,
        }
        with patch("app.api.video_generation.jobs.get_job", return_value=failed), patch(
            "app.api.video_generation.jobs.retry_failed_job",
            side_effect=ValueError("המשימה מיצתה את מספר הניסיונות המותר."),
        ):
            with self.assertRaises(HTTPException) as raised:
                retry_video_job(33, ConfirmedRetryRequest(confirmed=True))
        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
