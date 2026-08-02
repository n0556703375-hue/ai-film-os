import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.api.approvals import batch_approval
from app.models.schemas import BatchApprovalRequest
from app.repositories.batch_approvals import batch_approval as repository_batch_approval


class BatchApprovalTests(unittest.TestCase):
    def test_requires_media_id_for_decisions(self):
        with self.assertRaises(ValidationError):
            BatchApprovalRequest(project_id=1, action="approve", items=[{"shot_id": 1}])

    def test_finalize_rejects_media_id(self):
        with self.assertRaises(ValidationError):
            BatchApprovalRequest(
                project_id=1,
                action="finalize",
                items=[{"shot_id": 1, "media_id": 2}],
            )

    def test_rejects_duplicate_items(self):
        with self.assertRaises(ValidationError):
            BatchApprovalRequest(
                project_id=1,
                action="reject",
                items=[
                    {"shot_id": 1, "media_id": 2},
                    {"shot_id": 1, "media_id": 2},
                ],
            )

    def test_api_forwards_validated_batch(self):
        request = BatchApprovalRequest(
            project_id=9,
            action="approve",
            items=[{"shot_id": 1, "media_id": 4}],
            notes="ready",
        )
        with patch("app.api.approvals.batch_repo.batch_approval", return_value={"total": 1}) as mocked:
            result = batch_approval(request)
        self.assertEqual(result, {"total": 1})
        mocked.assert_called_once_with(
            action="approve",
            items=[{"shot_id": 1, "media_id": 4}],
            project_id=9,
            notes="ready",
        )

    def test_repository_isolates_blocked_items(self):
        with patch(
            "app.repositories.batch_approvals.decide_media",
            side_effect=[{"status": "תמונה מאושרת"}, ValueError("blocked")],
        ):
            result = repository_batch_approval(
                "approve",
                [
                    {"shot_id": 1, "media_id": 10},
                    {"shot_id": 2, "media_id": 20},
                ],
                9,
            )
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertTrue(result["results"][0]["ok"])
        self.assertFalse(result["results"][1]["ok"])

    def test_finalize_uses_existing_finalization_rules(self):
        with patch(
            "app.repositories.batch_approvals.finalize_shot",
            return_value={"status": "סופי"},
        ) as mocked:
            result = repository_batch_approval(
                "finalize",
                [{"shot_id": 7, "media_id": None}],
                9,
                "done",
            )
        mocked.assert_called_once_with(7, 9, "done")
        self.assertEqual(result["succeeded"], 1)


if __name__ == "__main__":
    unittest.main()
