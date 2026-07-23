import unittest
from unittest.mock import Mock, call, patch

from app.repositories import shots


class ShotReadQueryAdapterTests(unittest.TestCase):
    @patch("app.repositories.shots.execute_query")
    @patch("app.repositories.shots.get_connection")
    def test_filtered_shot_list_uses_query_adapter(self, get_connection, execute_query):
        connection = Mock()
        get_connection.return_value = connection
        execute_query.return_value.fetchall.return_value = [
            {"id": 5, "project_id": 9, "scene_id": 7, "shot_number": 2}
        ]

        result = shots.list_shots(project_id=9)

        self.assertEqual(result[0]["id"], 5)
        sql, params = execute_query.call_args.args[1:]
        self.assertIn("WHERE s.project_id=?", sql)
        self.assertEqual(params, (9,))
        connection.close.assert_called_once_with()

    @patch("app.repositories.shots.execute_query")
    @patch("app.repositories.shots.get_connection")
    def test_shot_detail_nested_reads_use_query_adapter(self, get_connection, execute_query):
        connection = Mock()
        get_connection.return_value = connection

        shot_cursor = Mock()
        shot_cursor.fetchone.return_value = {
            "id": 12,
            "project_id": 9,
            "scene_id": 7,
            "shot_number": 2,
            "title": "Current shot",
        }
        current_assets_cursor = Mock()
        current_assets_cursor.fetchall.return_value = [
            {
                "id": 20,
                "name": "Character",
                "master_reference_id": 30,
                "lock_status": "locked",
            }
        ]
        current_refs_cursor = Mock()
        current_refs_cursor.fetchall.return_value = [{"url": "https://example.invalid/ref"}]
        previous_cursor = Mock()
        previous_cursor.fetchone.return_value = {
            "id": 11,
            "shot_number": 1,
            "title": "Previous shot",
        }
        previous_assets_cursor = Mock()
        previous_assets_cursor.fetchall.return_value = []
        versions_cursor = Mock()
        versions_cursor.fetchall.return_value = [
            {"id": 40, "version": 1, "prompt": "Prompt", "negative_prompt": ""}
        ]
        media_cursor = Mock()
        media_cursor.fetchall.return_value = [
            {"id": 50, "metadata_json": '{"duration": 5}'}
        ]
        execute_query.side_effect = [
            shot_cursor,
            current_assets_cursor,
            current_refs_cursor,
            previous_cursor,
            previous_assets_cursor,
            versions_cursor,
            media_cursor,
        ]

        result = shots.get_shot(12)

        self.assertEqual(result["id"], 12)
        self.assertEqual(result["assets"][0]["reference_images"], ["https://example.invalid/ref"])
        self.assertEqual(result["previous_shot"]["id"], 11)
        self.assertEqual(result["media_results"][0]["metadata"], {"duration": 5})
        self.assertEqual(execute_query.call_count, 7)
        self.assertEqual(execute_query.call_args_list[0].args[2], (12,))
        self.assertEqual(execute_query.call_args_list[1].args[2], (12,))
        self.assertEqual(execute_query.call_args_list[2].args[2], (20, 30, "locked"))
        self.assertEqual(execute_query.call_args_list[3].args[2], (7, 2))
        self.assertEqual(execute_query.call_args_list[4].args[2], (11,))
        self.assertEqual(execute_query.call_args_list[5].args[2], (12,))
        self.assertEqual(execute_query.call_args_list[6].args[2], (12,))
        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
