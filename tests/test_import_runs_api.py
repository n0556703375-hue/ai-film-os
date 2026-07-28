import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.import_runs import (
    ImportRunPersistRequest,
    ImportRunStepRequest,
    persist_completed_import,
    process_next_import_chunk,
)


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

    @patch("app.api.import_runs.scene_repo.import_scenes")
    @patch("app.api.import_runs.scene_repo.list_scenes", return_value=[])
    @patch("app.api.import_runs.project_repo.get_project", return_value={"id": 7})
    def test_persists_completed_breakdown_once(self, _get_project, _list_scenes, import_scenes):
        import_scenes.return_value = [{"id": 11, "scene_number": 1, "title": "פתיחה"}]
        result = persist_completed_import(
            ImportRunPersistRequest(
                project_id=7,
                completed=True,
                scenes=[{"scene_number": 1, "title": "פתיחה"}],
            )
        )

        self.assertTrue(result["persisted"])
        self.assertFalse(result["idempotent_replay"])
        self.assertEqual(result["scenes_created"], 1)
        import_scenes.assert_called_once_with(
            7,
            [{"scene_number": 1, "title": "פתיחה"}],
            False,
        )

    @patch("app.api.import_runs.scene_repo.import_scenes")
    @patch(
        "app.api.import_runs.scene_repo.list_scenes",
        return_value=[{"id": 11, "project_id": 7, "scene_number": 1, "title": "פתיחה"}],
    )
    @patch("app.api.import_runs.project_repo.get_project", return_value={"id": 7})
    def test_repeated_persist_reuses_exact_existing_breakdown(self, _get_project, _list_scenes, import_scenes):
        result = persist_completed_import(
            ImportRunPersistRequest(
                project_id=7,
                completed=True,
                scenes=[{"scene_number": 1, "title": "פתיחה"}],
            )
        )

        self.assertFalse(result["persisted"])
        self.assertTrue(result["idempotent_replay"])
        import_scenes.assert_not_called()

    @patch("app.api.import_runs.scene_repo.import_scenes")
    @patch(
        "app.api.import_runs.scene_repo.list_scenes",
        return_value=[{"id": 11, "project_id": 7, "scene_number": 1, "title": "סצנה אחרת"}],
    )
    @patch("app.api.import_runs.project_repo.get_project", return_value={"id": 7})
    def test_rejects_persist_when_project_has_different_scenes(self, _get_project, _list_scenes, import_scenes):
        with self.assertRaises(HTTPException) as raised:
            persist_completed_import(
                ImportRunPersistRequest(
                    project_id=7,
                    completed=True,
                    scenes=[{"scene_number": 1, "title": "פתיחה"}],
                )
            )

        self.assertEqual(raised.exception.status_code, 409)
        import_scenes.assert_not_called()

    @patch("app.api.import_runs.scene_repo.import_scenes")
    @patch("app.api.import_runs.scene_repo.list_scenes", return_value=[])
    @patch("app.api.import_runs.project_repo.get_project", return_value={"id": 7})
    def test_rejects_duplicate_scene_signatures_before_write(self, _get_project, _list_scenes, import_scenes):
        with self.assertRaises(HTTPException) as raised:
            persist_completed_import(
                ImportRunPersistRequest(
                    project_id=7,
                    completed=True,
                    scenes=[
                        {"scene_number": 1, "title": "פתיחה"},
                        {"scene_number": 1, "title": "פתיחה"},
                    ],
                )
            )

        self.assertEqual(raised.exception.status_code, 409)
        import_scenes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
