import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deployment_smoke import SmokeConfig, SmokeFailure, run_smoke


class DeploymentSmokeShotMapGuardTests(unittest.TestCase):
    @patch("scripts.deployment_smoke._request_json")
    def test_import_rejects_shot_map_response_from_another_project(self, request_json):
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            request_json.side_effect = [
                {"status": "ok"},
                {"status": "ready"},
                {"project": {"id": 7}, "scenes": [], "shots": []},
                {
                    "screenplay_fingerprint": "f" * 64,
                    "next_chunk_index": 1,
                    "chunk_count": 1,
                    "completed": True,
                    "scenes": [
                        {
                            "scene_number": 1,
                            "title": "פתיחה",
                            "recommended_shot_count": 1,
                        }
                    ],
                },
                {
                    "persisted": True,
                    "idempotent_replay": False,
                    "scenes_created": 1,
                    "imported_scenes": [
                        {
                            "id": 11,
                            "project_id": 7,
                            "scene_number": 1,
                            "title": "פתיחה",
                            "recommended_shot_count": 1,
                        }
                    ],
                },
                {
                    "shots": [
                        {
                            "id": 21,
                            "project_id": 8,
                            "scene_id": 11,
                        }
                    ]
                },
            ]

            with self.assertRaisesRegex(SmokeFailure, "Shot-map.*another project"):
                run_smoke(
                    SmokeConfig(
                        base_url="https://example.invalid",
                        project_id=7,
                        screenplay_file=screenplay,
                        execute_import=True,
                    )
                )

        paths = [call.args[1] for call in request_json.call_args_list]
        self.assertEqual(paths.count("/api/scenes/11/shot-map"), 1)
        self.assertNotIn("/api/projects/7/production-snapshot", paths[6:])


if __name__ == "__main__":
    unittest.main()
