import unittest
from unittest.mock import Mock, call, patch

from app.repositories import scenes


class SceneReadQueryAdapterTests(unittest.TestCase):
    @patch("app.repositories.scenes.execute_query")
    @patch("app.repositories.scenes.get_connection")
    def test_filtered_scene_list_uses_query_adapter(self, get_connection, execute_query):
        connection = Mock()
        get_connection.return_value = connection
        execute_query.return_value.fetchall.return_value = [
            {"id": 4, "project_id": 9, "scene_number": 2, "title": "Scene"}
        ]

        result = scenes.list_scenes(project_id=9)

        self.assertEqual(result[0]["id"], 4)
        sql, params = execute_query.call_args.args[1:]
        self.assertIn("WHERE sc.project_id=?", sql)
        self.assertEqual(params, (9,))
        connection.close.assert_called_once_with()

    @patch("app.repositories.scenes.execute_query")
    @patch("app.repositories.scenes.get_connection")
    def test_scene_detail_and_shots_use_query_adapter(self, get_connection, execute_query):
        connection = Mock()
        get_connection.return_value = connection
        scene_cursor = Mock()
        scene_cursor.fetchone.return_value = {
            "id": 7,
            "project_id": 9,
            "scene_number": 3,
            "title": "Scene",
        }
        shots_cursor = Mock()
        shots_cursor.fetchall.return_value = [
            {"id": 12, "scene_id": 7, "shot_number": 1, "title": "Shot"}
        ]
        execute_query.side_effect = [scene_cursor, shots_cursor]

        result = scenes.get_scene(7)

        self.assertEqual(result["id"], 7)
        self.assertEqual(result["shots"][0]["id"], 12)
        self.assertEqual(
            execute_query.call_args_list,
            [
                call(connection, "SELECT * FROM scenes WHERE id=?", (7,)),
                call(connection, unittest.mock.ANY, (7,)),
            ],
        )
        self.assertIn("WHERE s.scene_id=?", execute_query.call_args_list[1].args[1])
        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
