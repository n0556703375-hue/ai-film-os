import unittest
from unittest.mock import call, patch

from app.api.scenes import create_shot_map
from app.models.schemas import ShotMapRequest


class ShotMapProjectIsolationTests(unittest.TestCase):
    @patch("app.api.scenes.build_prompt")
    @patch("app.api.scenes.generate_shot_map")
    @patch("app.api.scenes.shot_repo.update_shot")
    @patch("app.api.scenes.shot_repo.save_prompt_version")
    @patch("app.api.scenes.shot_repo.get_shot")
    @patch("app.api.scenes.asset_repo.list_assets")
    @patch("app.api.scenes.project_repo.get_project")
    @patch("app.api.scenes.repo.create_generated_shots")
    @patch("app.api.scenes.repo.get_scene")
    def test_two_projects_generate_shot_maps_without_cross_project_reads_or_writes(
        self,
        get_scene,
        create_generated_shots,
        get_project,
        list_assets,
        get_shot,
        save_prompt_version,
        update_shot,
        generate_shot_map,
        build_prompt,
    ):
        scenes = {
            701: {"id": 701, "project_id": 7, "scene_number": 1, "title": "A"},
            801: {"id": 801, "project_id": 8, "scene_number": 1, "title": "B"},
        }
        projects = {7: {"id": 7}, 8: {"id": 8}}
        assets = {
            7: [{"id": 71, "project_id": 7, "approved": True}],
            8: [{"id": 81, "project_id": 8, "approved": True}],
        }

        get_scene.side_effect = lambda scene_id: scenes.get(scene_id)
        get_project.side_effect = lambda project_id: projects.get(project_id)
        list_assets.side_effect = lambda project_id: list(assets[project_id])
        generate_shot_map.side_effect = lambda scene, project, approved_assets, count: [
            {
                "shot_number": 1,
                "title": f"shot-{scene['project_id']}",
                "project_id": scene["project_id"],
            }
        ]

        def persist(scene_id, generated, replace_existing):
            self.assertFalse(replace_existing)
            project_id = scenes[scene_id]["project_id"]
            self.assertTrue(all(item["project_id"] == project_id for item in generated))
            return {"shots": [{"id": scene_id * 10 + 1}]}

        create_generated_shots.side_effect = persist
        get_shot.side_effect = lambda shot_id: {
            "id": shot_id,
            "negative_prompt": "",
        }
        build_prompt.side_effect = lambda shot: f"prompt-{shot['id']}"

        create_shot_map(701, ShotMapRequest(shot_count=1, replace_existing=False))
        create_shot_map(801, ShotMapRequest(shot_count=1, replace_existing=False))

        self.assertEqual(get_project.call_args_list, [call(7), call(8)])
        self.assertEqual(list_assets.call_args_list, [call(7), call(8)])
        self.assertEqual(create_generated_shots.call_args_list[0].args[0], 701)
        self.assertEqual(create_generated_shots.call_args_list[1].args[0], 801)
        self.assertEqual(generate_shot_map.call_args_list[0].args[2], assets[7])
        self.assertEqual(generate_shot_map.call_args_list[1].args[2], assets[8])
        self.assertEqual(save_prompt_version.call_count, 2)
        self.assertEqual(update_shot.call_count, 2)


if __name__ == "__main__":
    unittest.main()
