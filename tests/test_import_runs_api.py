import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.import_runs import ImportRunStepRequest, process_next_import_chunk


class ImportRunsApiTests(unittest.TestCase):
    @patch("app.api.import_runs.process_next_chunk")
    @patch("app.api.import_runs.project_repo.get_project", return_value={"id": 7})
    def test_processes_one_chunk_and_returns_progress(self, _get_project, process_next):
        def advance(_project, state):
            state.scenes.append({"title": "סצנה א"})
            state.next_chunk_index += 1
            return state

        process_next.side_effect = advance
        result = process_next_import_chunk(
            ImportRunStepRequest(project_id=7, screenplay="א" * 80)
        )

        self.assertEqual(result["project_id"], 7)
        self.assertEqual(result["processed_chunks"], 1)
        self.assertEqual(result["scenes"], [{"title": "סצנה א"}])
        process_next.assert_called_once()

    @patch("app.api.import_runs.project_repo.get_project", return_value=None)
    def test_rejects_missing_project_before_provider_call(self, _get_project):
        with self.assertRaises(HTTPException) as raised:
            process_next_import_chunk(
                ImportRunStepRequest(project_id=7, screenplay="א" * 80)
            )
        self.assertEqual(raised.exception.status_code, 404)

    @patch("app.api.import_runs.project_repo.get_project", return_value={"id": 7})
    def test_rejects_impossible_resume_index(self, _get_project):
        with self.assertRaises(HTTPException) as raised:
            process_next_import_chunk(
                ImportRunStepRequest(
                    project_id=7,
                    screenplay="א" * 80,
                    next_chunk_index=2,
                )
            )
        self.assertEqual(raised.exception.status_code, 409)

    @patch("app.api.import_runs.process_next_chunk", side_effect=RuntimeError("provider payload"))
    @patch("app.api.import_runs.project_repo.get_project", return_value={"id": 7})
    def test_provider_failure_returns_retryable_sanitized_progress(self, _get_project, _process_next):
        with self.assertRaises(HTTPException) as raised:
            process_next_import_chunk(
                ImportRunStepRequest(project_id=7, screenplay="א" * 80)
            )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail["code"], "screenplay_chunk_failure")
        self.assertTrue(raised.exception.detail["retryable"])
        self.assertNotIn("provider payload", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
