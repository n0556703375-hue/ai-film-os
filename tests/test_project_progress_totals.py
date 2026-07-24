import unittest
from unittest.mock import Mock, call, patch

from app.repositories import projects


class ProjectProgressTotalsTests(unittest.TestCase):
    @patch("app.repositories.projects.execute_query")
    @patch("app.repositories.projects.get_connection")
    def test_list_projects_includes_shot_status_totals(self, get_connection, execute_query):
        connection = Mock()
        get_connection.return_value = connection

        projects_cursor = Mock()
        projects_cursor.fetchall.return_value = [
            {
                "id": 7,
                "name": "Film",
                "scenes_total": 4,
                "shots_total": 9,
                "assets_total": 3,
            },
            {
                "id": 8,
                "name": "Empty film",
                "scenes_total": 0,
                "shots_total": 0,
                "assets_total": 0,
            },
        ]
        status_cursor = Mock()
        status_cursor.fetchall.return_value = [
            {"project_id": 7, "status": "פרומפט מוכן", "total": 5},
            {"project_id": 7, "status": "טיוטת תמונה", "total": 3},
            {"project_id": 7, "status": None, "total": 1},
        ]
        execute_query.side_effect = [projects_cursor, status_cursor]

        result = projects.list_projects()

        self.assertEqual(
            result[0]["shot_status_totals"],
            {"פרומפט מוכן": 5, "טיוטת תמונה": 3, "not_started": 1},
        )
        self.assertEqual(result[1]["shot_status_totals"], {})
        self.assertEqual(execute_query.call_count, 2)
        self.assertIn("COUNT(*) FROM scenes", execute_query.call_args_list[0].args[1])
        self.assertIn("GROUP BY project_id, status", execute_query.call_args_list[1].args[1])
        connection.close.assert_called_once_with()

    @patch("app.repositories.projects.execute_query")
    @patch("app.repositories.projects.get_connection")
    def test_project_progress_reads_use_cross_backend_query_adapter(
        self, get_connection, execute_query
    ):
        connection = Mock()
        get_connection.return_value = connection
        execute_query.side_effect = [
            Mock(fetchall=Mock(return_value=[])),
            Mock(fetchall=Mock(return_value=[])),
        ]

        projects.list_projects()

        self.assertEqual(
            execute_query.call_args_list,
            [call(connection, unittest.mock.ANY), call(connection, unittest.mock.ANY)],
        )


if __name__ == "__main__":
    unittest.main()
