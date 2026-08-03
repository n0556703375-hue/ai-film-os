import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deployment_smoke import SmokeConfig, run_smoke


class DeploymentSmokeSequentialIdempotencyTests(unittest.TestCase):
    @patch("scripts.deployment_smoke._request_json")
    def test_two_sequential_import_runs_preserve_counts_and_skip_second_shot_map(self, request_json):
        state = {
            "persisted": False,
            "shots_created": False,
            "shot_map_calls": 0,
        }

        def fake_request(config, path, *, method="GET", payload=None, query=None):
            del config, method, payload, query
            if path == "/health":
                return {"status": "ok"}
            if path == "/ready":
                return {"status": "ready"}
            if path == "/api/projects/7/production-snapshot":
                scenes = [{"id": 11, "project_id": 7}] if state["persisted"] else []
                shots = (
                    [{"id": 21, "project_id": 7, "scene_id": 11}]
                    if state["shots_created"]
                    else []
                )
                return {"project": {"id": 7}, "scenes": scenes, "shots": shots}
            if path == "/api/import-runs/process-next":
                return {
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
                }
            if path == "/api/import-runs/persist":
                replay = state["persisted"]
                state["persisted"] = True
                return {
                    "persisted": not replay,
                    "idempotent_replay": replay,
                    "scenes_created": 0 if replay else 1,
                    "imported_scenes": [
                        {
                            "id": 11,
                            "project_id": 7,
                            "scene_number": 1,
                            "title": "פתיחה",
                            "recommended_shot_count": 1,
                        }
                    ],
                }
            if path == "/api/scenes/11/shot-map":
                state["shot_map_calls"] += 1
                state["shots_created"] = True
                return {"shots": [{"id": 21, "project_id": 7, "scene_id": 11}]}
            raise AssertionError(f"Unexpected smoke request: {path}")

        request_json.side_effect = fake_request

        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            config = SmokeConfig(
                base_url="https://example.invalid",
                project_id=7,
                screenplay_file=screenplay,
                execute_import=True,
            )

            first = run_smoke(config)
            second = run_smoke(config)

        self.assertEqual(first["after"], {"scenes": 1, "shots": 1})
        self.assertFalse(first["idempotent_replay"])
        self.assertEqual(first["shots_created"], 1)

        self.assertEqual(second["before"], {"scenes": 1, "shots": 1})
        self.assertEqual(second["after"], {"scenes": 1, "shots": 1})
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(second["shots_created"], 0)
        self.assertEqual(second["shot_maps_skipped"], 1)
        self.assertEqual(state["shot_map_calls"], 1)


if __name__ == "__main__":
    unittest.main()
