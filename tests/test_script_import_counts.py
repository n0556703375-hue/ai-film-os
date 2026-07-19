import unittest
from unittest.mock import patch

from app.api.scenes import import_script
from app.models.schemas import ScriptImportRequest


class ScriptImportCountTests(unittest.TestCase):
    @patch("app.api.scenes.repo.list_scenes", return_value=[])
    @patch("app.api.scenes.shot_repo.update_shot")
    @patch("app.api.scenes.shot_repo.save_prompt_version")
    @patch("app.api.scenes.build_prompt", return_value="prompt")
    @patch("app.api.scenes.shot_repo.get_shot", return_value={"negative_prompt": ""})
    @patch("app.api.scenes.repo.create_generated_shots")
    @patch("app.api.scenes.generate_shot_map", return_value=[{"title": "A"}, {"title": "B"}])
    @patch("app.api.scenes.repo.get_scene", return_value={"id": 10, "project_id": 1})
    @patch("app.api.scenes.repo.import_scenes")
    @patch("app.api.scenes.breakdown_screenplay", return_value=[{"scene_number": 1}])
    @patch("app.api.scenes.asset_repo.list_assets", return_value=[])
    @patch("app.api.scenes.project_repo.get_project", return_value={"id": 1, "name": "Test"})
    def test_reports_actual_created_shot_count(
        self,
        _get_project,
        _list_assets,
        _breakdown,
        import_scenes,
        _get_scene,
        _generate_shot_map,
        create_generated_shots,
        _get_shot,
        _build_prompt,
        _save_prompt_version,
        _update_shot,
        _list_scenes,
    ):
        import_scenes.return_value = [
            {"id": 10, "recommended_shot_count": 6},
        ]
        create_generated_shots.return_value = {
            "shots": [{"id": 101}, {"id": 102}],
        }

        result = import_script(
            ScriptImportRequest(
                project_id=1,
                screenplay="Scene text " * 10,
                generate_shot_maps=True,
            )
        )

        self.assertEqual(result["shots_created"], 2)


if __name__ == "__main__":
    unittest.main()
