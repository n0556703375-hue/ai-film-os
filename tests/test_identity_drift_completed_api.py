import json
import unittest
from unittest.mock import Mock, patch

from app.api.identity_assessments import list_completed_identity_drift


class IdentityDriftCompletedApiTests(unittest.TestCase):
    @patch("app.api.identity_assessments.get_connection")
    def test_returns_only_safe_completed_summaries(self, get_connection):
        connection = Mock()
        get_connection.return_value = connection
        cursor = Mock()
        cursor.fetchall.return_value = [
            {
                "id": 12,
                "shot_id": 8,
                "media_type": "image",
                "url": "https://example.invalid/frame-12.png",
                "metadata_json": json.dumps({
                    "identity_drift": {
                        "status": "passed",
                        "passed": True,
                        "score": 0.98,
                        "worker_id": "identity-worker-1",
                        "attempt": 2,
                        "completed_at": "2026-07-26T06:00:00+00:00",
                        "evidence": {"raw_provider_payload": "secret-ish"},
                    }
                }),
            },
            {
                "id": 11,
                "shot_id": 7,
                "media_type": "image",
                "url": "https://example.invalid/frame-11.png",
                "metadata_json": json.dumps({
                    "identity_drift": {"status": "running"}
                }),
            },
            {
                "id": 10,
                "shot_id": 6,
                "media_type": "image",
                "url": "https://example.invalid/frame-10.png",
                "metadata_json": "not-json",
            },
        ]
        connection.execute.return_value = cursor

        result = list_completed_identity_drift(limit=50)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["media_id"], 12)
        summary = result["items"][0]["identity_drift"]
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["worker_id"], "identity-worker-1")
        self.assertNotIn("evidence", summary)
        self.assertNotIn("raw_provider_payload", summary)
        sql = connection.execute.call_args.args[0]
        self.assertIn("WHERE media_results.media_type IN ('image', 'video')", sql)
        self.assertIn("ORDER BY media_results.id DESC", sql)
        connection.close.assert_called_once_with()

    @patch("app.api.identity_assessments.get_connection")
    def test_limit_applies_to_completed_items_not_scanned_rows(self, get_connection):
        connection = Mock()
        get_connection.return_value = connection
        cursor = Mock()
        cursor.fetchall.return_value = [
            {
                "id": 3,
                "shot_id": 3,
                "media_type": "image",
                "url": "https://example.invalid/3.png",
                "metadata_json": json.dumps({
                    "identity_drift": {"status": "running"}
                }),
            },
            {
                "id": 2,
                "shot_id": 2,
                "media_type": "image",
                "url": "https://example.invalid/2.png",
                "metadata_json": json.dumps({
                    "identity_drift": {"status": "blocked", "passed": False}
                }),
            },
            {
                "id": 1,
                "shot_id": 1,
                "media_type": "image",
                "url": "https://example.invalid/1.png",
                "metadata_json": json.dumps({
                    "identity_drift": {"status": "error", "passed": False}
                }),
            },
        ]
        connection.execute.return_value = cursor

        result = list_completed_identity_drift(limit=1)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["media_id"], 2)


if __name__ == "__main__":
    unittest.main()
