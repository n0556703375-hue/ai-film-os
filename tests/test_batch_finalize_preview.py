import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.api.approvals import preview_batch_finalize as preview_endpoint
from app.models.schemas import BatchFinalizePreviewRequest
from app.repositories.approvals import preview_batch_finalize


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    def execute(self, query, params):
        shot_id = params[0]
        if "FROM shots" in query:
            if shot_id == 404:
                return _Cursor(None)
            status = "סופי" if shot_id == 3 else "וידאו מאושר"
            return _Cursor({"id": shot_id, "status": status})
        if "media_type='image'" in query:
            return _Cursor({"ok": 1} if shot_id in {1, 3} else None)
        if "media_type='video'" in query:
            return _Cursor({"ok": 1} if shot_id in {1, 3} else None)
        if "FROM continuity_issues" in query:
            return _Cursor({"severity": "high", "message": "blocker"} if shot_id == 2 else None)
        raise AssertionError(query)


class BatchFinalizePreviewTests(unittest.TestCase):
    def test_schema_requires_non_empty_bounded_list(self):
        with self.assertRaises(ValidationError):
            BatchFinalizePreviewRequest(project_id=1, shot_ids=[])
        with self.assertRaises(ValidationError):
            BatchFinalizePreviewRequest(project_id=1, shot_ids=list(range(101)))

    def test_preview_is_read_only_deduplicated_and_reports_blockers(self):
        conn = _Connection()
        with patch("app.repositories.approvals.get_connection", return_value=conn):
            result = preview_batch_finalize([1, 2, 1, 3, 404], 9)

        self.assertTrue(conn.closed)
        self.assertEqual(result["requested"], 5)
        self.assertEqual(result["unique"], 4)
        self.assertEqual(result["eligible"], 2)
        self.assertEqual(result["items"][0]["shot_id"], 1)
        self.assertTrue(result["items"][0]["eligible"])
        self.assertFalse(result["items"][1]["eligible"])
        self.assertIn("חסרה תמונה מאושרת.", result["items"][1]["reasons"])
        self.assertIn("קיימת בעיית רציפות חוסמת.", result["items"][1]["reasons"])
        self.assertTrue(result["items"][2]["already_final"])
        self.assertEqual(result["items"][3]["reasons"], ["השוט לא נמצא."])

    def test_endpoint_forwards_validated_ids(self):
        request = BatchFinalizePreviewRequest(project_id=3, shot_ids=[8, 9])
        expected = {"requested": 2, "unique": 2, "eligible": 0, "items": []}
        with patch("app.api.approvals.repo.preview_batch_finalize", return_value=expected) as preview:
            result = preview_endpoint(request)
        preview.assert_called_once_with([8, 9], 3)
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
