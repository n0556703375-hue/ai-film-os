import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.api.approvals import finalize_batch as finalize_batch_endpoint
from app.models.schemas import BatchFinalizeRequest
from app.repositories.approvals import finalize_batch


class BatchFinalizeTests(unittest.TestCase):
    def test_schema_requires_explicit_true_confirmation(self):
        with self.assertRaises(ValidationError):
            BatchFinalizeRequest(project_id=1, shot_ids=[1], confirmed=False)
        request = BatchFinalizeRequest(
            project_id=1, shot_ids=[1], confirmed=True, notes="approved batch"
        )
        self.assertTrue(request.confirmed)

    def test_batch_is_partial_deduplicated_and_preserves_blockers(self):
        preview = {
            "requested": 5,
            "unique": 4,
            "eligible": 2,
            "items": [
                {"shot_id": 1, "eligible": True, "reasons": [], "already_final": False},
                {"shot_id": 2, "eligible": False, "reasons": ["חסר וידאו מאושר."], "already_final": False},
                {"shot_id": 3, "eligible": True, "reasons": [], "already_final": True},
                {"shot_id": 4, "eligible": True, "reasons": [], "already_final": False},
            ],
        }
        with patch("app.repositories.approvals.preview_batch_finalize", return_value=preview), patch(
            "app.repositories.approvals.finalize_shot",
            side_effect=[{"status": "סופי"}, ValueError("קיימת בעיית רציפות חוסמת.")],
        ) as finalize:
            result = finalize_batch([1, 2, 1, 3, 4], 9, "batch note")

        self.assertEqual(finalize.call_count, 2)
        self.assertEqual(result["requested"], 5)
        self.assertEqual(result["unique"], 4)
        self.assertEqual(result["finalized"], 1)
        self.assertEqual(result["blocked"], 2)
        self.assertEqual(result["already_final"], 1)
        self.assertEqual([item["status"] for item in result["items"]], [
            "finalized", "blocked", "already_final", "blocked"
        ])

    def test_endpoint_forwards_confirmed_request(self):
        request = BatchFinalizeRequest(project_id=3, shot_ids=[8, 9], confirmed=True, notes="ready")
        expected = {
            "requested": 2,
            "unique": 2,
            "finalized": 2,
            "blocked": 0,
            "already_final": 0,
            "items": [],
        }
        with patch("app.api.approvals.repo.finalize_batch", return_value=expected) as batch:
            result = finalize_batch_endpoint(request)
        batch.assert_called_once_with([8, 9], 3, "ready")
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
