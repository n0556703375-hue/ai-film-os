import unittest
from unittest.mock import Mock, call, patch

from app.repositories import shots


class CharacterLockReferenceFlowTests(unittest.TestCase):
    @patch("app.repositories.shots.execute_query")
    def test_only_locked_approved_master_reference_flows_into_shot_generation(self, execute_query):
        asset_rows = Mock()
        asset_rows.fetchall.return_value = [
            {
                "id": 11,
                "asset_type": "דמות",
                "name": "Lead",
                "lock_status": "locked",
                "master_reference_id": 101,
            },
            {
                "id": 12,
                "asset_type": "דמות",
                "name": "Draft character",
                "lock_status": "review",
                "master_reference_id": 102,
            },
        ]
        locked_reference = Mock()
        locked_reference.fetchall.return_value = [{"url": "https://example.com/master.jpg"}]
        unlocked_reference = Mock()
        unlocked_reference.fetchall.return_value = []
        execute_query.side_effect = [asset_rows, locked_reference, unlocked_reference]

        result = shots._load_assets(Mock(), shot_id=7)

        self.assertEqual(result[0]["reference_images"], ["https://example.com/master.jpg"])
        self.assertEqual(result[1]["reference_images"], [])

        reference_query = execute_query.call_args_list[1].args[1]
        self.assertIn("r.approved=1", reference_query)
        self.assertIn("r.id=?", reference_query)
        self.assertIn("?='locked'", reference_query)
        self.assertEqual(
            execute_query.call_args_list[1].args[2],
            (11, 101, "locked"),
        )
        self.assertEqual(
            execute_query.call_args_list[2].args[2],
            (12, 102, "review"),
        )


if __name__ == "__main__":
    unittest.main()
