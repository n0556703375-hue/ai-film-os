import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api.shots import list_shots
from app.repositories.shots import normalize_pipeline_status


class ShotPipelineFilterTests(unittest.TestCase):
    def test_normalizes_english_pipeline_aliases(self):
        self.assertEqual(normalize_pipeline_status("image_draft"), "תמונת טיוטה")
        self.assertEqual(normalize_pipeline_status("final"), "סופי")

    def test_accepts_canonical_hebrew_status(self):
        self.assertEqual(normalize_pipeline_status("וידאו מאושר"), "וידאו מאושר")

    def test_rejects_unknown_pipeline_status(self):
        with self.assertRaisesRegex(ValueError, "סטטוס מסלול האישור אינו תקין"):
            normalize_pipeline_status("unknown")

    def test_api_forwards_project_and_pipeline_filters(self):
        with patch("app.api.shots.repo.list_shots", return_value=[]) as mocked:
            result = list_shots(project_id=7, pipeline_status="image_approved")
        self.assertEqual(result, [])
        mocked.assert_called_once_with(7, "image_approved")

    def test_api_returns_400_for_invalid_filter(self):
        with patch(
            "app.api.shots.repo.list_shots",
            side_effect=ValueError("סטטוס מסלול האישור אינו תקין."),
        ):
            with self.assertRaises(HTTPException) as raised:
                list_shots(project_id=7, pipeline_status="bad")
        self.assertEqual(raised.exception.status_code, 400)

    def test_repository_combines_project_and_status_without_mutation(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.close = MagicMock()
        with patch("app.repositories.shots.get_connection", return_value=connection), patch(
            "app.repositories.shots.execute_query", return_value=cursor
        ) as execute:
            from app.repositories.shots import list_shots as repository_list_shots

            result = repository_list_shots(4, "video_draft")

        self.assertEqual(result, [])
        query, params = execute.call_args.args[1], execute.call_args.args[2]
        self.assertIn("s.project_id=?", query)
        self.assertIn("s.status=?", query)
        self.assertEqual(params, (4, "וידאו טיוטה"))


if __name__ == "__main__":
    unittest.main()
