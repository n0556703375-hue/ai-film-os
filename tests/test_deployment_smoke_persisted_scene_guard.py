import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deployment_smoke import SmokeConfig, SmokeFailure, _run_resumable_import


class PersistedSceneProjectGuardTests(unittest.TestCase):
    @patch("scripts.deployment_smoke._request_json")
    def test_rejects_cross_project_persisted_scene_before_shot_map_write(self, request_json):
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            request_json.side_effect = [
                {
                    "screenplay_fingerprint": "f" * 64,
                    "next_chunk_index": 1,
                    "chunk_count": 1,
                    "completed": True,
                    "scenes": [
                        {
                            "scene_number": 1,
                            "title": "פתיחה",
                            "recommended_shot_count": 2,
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
                            "project_id": 8,
                            "scene_number": 1,
                            "title": "פתיחה",
                            "recommended_shot_count": 2,
                        }
                    ],
                },
            ]

            config = SmokeConfig(
                base_url="https://example.invalid",
                project_id=7,
                screenplay_file=screenplay,
                execute_import=True,
            )
            with self.assertRaisesRegex(SmokeFailure, "scene from another project"):
                _run_resumable_import(config)

        paths = [call.args[1] for call in request_json.call_args_list]
        self.assertEqual(
            paths,
            ["/api/import-runs/process-next", "/api/import-runs/persist"],
        )
        self.assertFalse(any(path.endswith("/shot-map") for path in paths))


if __name__ == "__main__":
    unittest.main()
