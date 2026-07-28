import unittest
from unittest.mock import patch

from app.api.import_runs import ImportRunPersistRequest, persist_completed_import


class ImportRunsProjectIsolationTests(unittest.TestCase):
    @patch("app.api.import_runs.scene_repo.import_scenes")
    @patch("app.api.import_runs.scene_repo.list_scenes")
    @patch("app.api.import_runs.project_repo.get_project")
    def test_two_projects_persist_independent_scene_sets(
        self,
        get_project,
        list_scenes,
        import_scenes,
    ):
        projects = {7: {"id": 7}, 8: {"id": 8}}
        stored = {7: [], 8: []}

        get_project.side_effect = lambda project_id: projects.get(project_id)
        list_scenes.side_effect = lambda project_id: list(stored[project_id])

        def persist(project_id, scenes, replace_existing):
            self.assertFalse(replace_existing)
            created = [
                {
                    **scene,
                    "id": project_id * 100 + index,
                    "project_id": project_id,
                }
                for index, scene in enumerate(scenes, start=1)
            ]
            stored[project_id].extend(created)
            return created

        import_scenes.side_effect = persist

        first = persist_completed_import(
            ImportRunPersistRequest(
                project_id=7,
                completed=True,
                scenes=[{"scene_number": 1, "title": "Project A opening"}],
            )
        )
        second = persist_completed_import(
            ImportRunPersistRequest(
                project_id=8,
                completed=True,
                scenes=[{"scene_number": 1, "title": "Project B opening"}],
            )
        )

        self.assertTrue(first["persisted"])
        self.assertTrue(second["persisted"])
        self.assertEqual(first["imported_scenes"][0]["project_id"], 7)
        self.assertEqual(second["imported_scenes"][0]["project_id"], 8)
        self.assertEqual([scene["title"] for scene in stored[7]], ["Project A opening"])
        self.assertEqual([scene["title"] for scene in stored[8]], ["Project B opening"])
        self.assertEqual(list_scenes.call_args_list[0].args, (7,))
        self.assertEqual(list_scenes.call_args_list[1].args, (8,))
        self.assertEqual(import_scenes.call_args_list[0].args[0], 7)
        self.assertEqual(import_scenes.call_args_list[1].args[0], 8)


if __name__ == "__main__":
    unittest.main()
