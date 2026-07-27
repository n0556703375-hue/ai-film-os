import unittest
from unittest.mock import MagicMock, patch

from app.repositories import jobs


class JobIdempotencyTests(unittest.TestCase):
    def _existing_job(self, status):
        return {
            "id": 41,
            "project_id": 2,
            "shot_id": 7,
            "job_type": "video",
            "status": status,
            "payload_json": '{"duration_seconds": 5}',
            "result_json": "{}",
            "idempotency_key": "shot:7:video:abc",
            "max_attempts": 3,
            "attempts": 2,
            "worker_id": "",
            "last_error": "temporary failure",
            "estimated_cost_usd": 0,
            "actual_cost_usd": 0,
            "priority": 0,
            "started_at": None,
            "finished_at": None,
            "created_at": None,
            "updated_at": None,
        }

    def _connection_with_existing(self, status):
        conn = MagicMock()
        shot_result = MagicMock()
        shot_result.fetchone.return_value = {"exists": 1}
        existing_result = MagicMock()
        existing_result.fetchone.return_value = self._existing_job(status)
        conn.execute.side_effect = [shot_result, existing_result]
        return conn

    def test_duplicate_failed_submission_does_not_reset_attempts(self):
        conn = self._connection_with_existing("failed")
        with patch("app.repositories.jobs.get_connection", return_value=conn):
            job, created = jobs.enqueue_job(
                2, 7, "video", {"duration_seconds": 5}, "shot:7:video:abc"
            )

        self.assertFalse(created)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["attempts"], 2)
        self.assertEqual(conn.execute.call_count, 2)
        conn.commit.assert_not_called()

    def test_duplicate_cancelled_submission_does_not_requeue(self):
        conn = self._connection_with_existing("cancelled")
        with patch("app.repositories.jobs.get_connection", return_value=conn):
            job, created = jobs.enqueue_job(
                2, 7, "video", {"duration_seconds": 5}, "shot:7:video:abc"
            )

        self.assertFalse(created)
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["attempts"], 2)
        conn.commit.assert_not_called()

    def test_duplicate_completed_submission_remains_idempotent(self):
        conn = self._connection_with_existing("completed")
        with patch("app.repositories.jobs.get_connection", return_value=conn):
            job, created = jobs.enqueue_job(
                2, 7, "video", {"duration_seconds": 5}, "shot:7:video:abc"
            )

        self.assertFalse(created)
        self.assertEqual(job["status"], "completed")
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
