import json
import unittest
from unittest.mock import patch

from app.api.identity_assessments import _store_identity_drift


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self):
        self.saved_metadata = None
        self.committed = False
        self.closed = False
        self.media = {
            "id": 20,
            "shot_id": 10,
            "media_type": "image",
            "url": "https://example.invalid/frame.png",
            "metadata_json": json.dumps({
                "identity_drift": {
                    "status": "running",
                    "worker_id": "identity-worker-1",
                    "attempt": 2,
                    "claimed_at": "2026-07-25T20:00:00+00:00",
                }
            }),
        }

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT * FROM media_results WHERE id=? AND shot_id=?"):
            return _Result(dict(self.media))
        if normalized.startswith("UPDATE media_results SET metadata_json=? WHERE id=?"):
            self.saved_metadata = params[0]
            self.media["metadata_json"] = params[0]
            return _Result(None)
        if normalized.startswith("SELECT * FROM media_results WHERE id=?"):
            return _Result(dict(self.media))
        raise AssertionError(f"Unexpected SQL: {normalized}")

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class IdentityDriftCompletionAuditWiringTests(unittest.TestCase):
    @patch("app.api.identity_assessments.build_completed_identity_drift_assessment")
    @patch("app.api.identity_assessments.get_connection")
    def test_store_persists_audited_completion_result(self, get_connection, build_completed):
        connection = _Connection()
        get_connection.return_value = connection
        completed = {
            "status": "passed",
            "passed": True,
            "score": 0.98,
            "worker_id": "identity-worker-1",
            "attempt": 2,
            "claimed_at": "2026-07-25T20:00:00+00:00",
            "completed_at": "2026-07-25T20:05:00+00:00",
        }
        build_completed.return_value = completed

        result = _store_identity_drift(
            10,
            20,
            {"status": "passed", "passed": True, "score": 0.98},
            "identity-worker-1",
        )

        current = json.loads(connection.media["metadata_json"])["identity_drift"]
        build_completed.assert_called_once()
        self.assertEqual(build_completed.call_args.args[2], "identity-worker-1")
        self.assertEqual(current, completed)
        self.assertTrue(connection.committed)
        self.assertEqual(result["media"]["metadata"]["identity_drift"], completed)


if __name__ == "__main__":
    unittest.main()
