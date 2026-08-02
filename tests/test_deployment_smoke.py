import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.health import health
from app.core.version import APP_VERSION
from scripts.deployment_smoke import (
    SmokeConfig,
    SmokeFailure,
    _scene_ids_with_shots,
    _snapshot_counts,
    build_import_payload,
    run_smoke,
)


class DeploymentSmokeTests(unittest.TestCase):
    def test_application_and_health_report_same_version(self):
        from app.main import app

        payload = health()
        self.assertEqual(app.version, APP_VERSION)
        self.assertEqual(payload["version"], APP_VERSION)
        self.assertEqual(payload["status"], "ok")

    def test_required_deployment_routes_are_registered(self):
        from app.api.health import router as health_router
        from app.api.import_runs import router as import_runs_router
        from app.api.scenes import router as scenes_router
        from app.api.video_generation import router as video_generation_router

        paths = {
            route.path
            for router in (
                health_router,
                import_runs_router,
                scenes_router,
                video_generation_router,
            )
            for route in router.routes
            if isinstance(getattr(route, "path", None), str)
        }
        self.assertIn("/health", paths)
        self.assertIn("/ready", paths)
        self.assertIn("/api/import-runs/process-next", paths)
        self.assertIn("/api/import-runs/persist", paths)
        self.assertIn("/api/scenes/{scene_id}/shot-map", paths)
        self.assertIn("/api/video-generation/jobs/{job_id}/status", paths)

    def test_import_requires_explicit_execution_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            config = SmokeConfig(
                base_url="https://example.invalid",
                project_id=7,
                screenplay_file=screenplay,
                execute_import=False,
            )
            with self.assertRaisesRegex(SmokeFailure, "--execute-import"):
                build_import_payload(config)

    def test_import_payload_starts_a_bounded_non_destructive_run(self):
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            payload = build_import_payload(
                SmokeConfig(
                    base_url="https://example.invalid",
                    project_id=7,
                    screenplay_file=screenplay,
                    execute_import=True,
                )
            )
        self.assertEqual(payload["project_id"], 7)
        self.assertEqual(payload["next_chunk_index"], 0)
        self.assertEqual(payload["scenes"], [])
        self.assertEqual(payload["screenplay_fingerprint"], "")
        self.assertNotIn("replace_existing", payload)

    def test_snapshot_rejects_cross_project_scene_or_shot(self):
        with self.assertRaisesRegex(SmokeFailure, "scene from another project"):
            _snapshot_counts({
                "project": {"id": 7},
                "scenes": [{"id": 1, "project_id": 8}],
                "shots": [],
            })
        with self.assertRaisesRegex(SmokeFailure, "shot from another project"):
            _snapshot_counts({
                "project": {"id": 7},
                "scenes": [],
                "shots": [{"id": 2, "project_id": 8}],
            })

    def test_snapshot_rejects_invalid_shot_scene_relationship(self):
        with self.assertRaisesRegex(SmokeFailure, "invalid scene relationship"):
            _scene_ids_with_shots({
                "project": {"id": 7},
                "scenes": [{"id": 11, "project_id": 7}],
                "shots": [{"id": 21, "project_id": 7, "scene_id": 99}],
            })

    @patch("scripts.deployment_smoke._request_json")
    def test_default_run_is_read_only(self, request_json):
        request_json.side_effect = [
            {"status": "ok"},
            {"status": "ready"},
            {
                "project": {"id": 7},
                "scenes": [{"id": 1, "project_id": 7}],
                "shots": [{"id": 2, "project_id": 7, "scene_id": 1}],
            },
        ]
        result = run_smoke(SmokeConfig(base_url="https://example.invalid", project_id=7))
        self.assertFalse(result["import_executed"])
        self.assertEqual(result["before"], {"scenes": 1, "shots": 1})
        self.assertEqual(
            [call.kwargs.get("method", "GET") for call in request_json.call_args_list],
            ["GET", "GET", "GET"],
        )

    @patch("scripts.deployment_smoke._request_json")
    def test_import_run_uses_resumable_non_replacing_flow(self, request_json):
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
                    "scenes": [{"scene_number": 1, "title": "פתיחה", "recommended_shot_count": 2}],
                },
                {
                    "persisted": True,
                    "idempotent_replay": False,
                    "scenes_created": 1,
                    "imported_scenes": [
                        {"id": 11, "project_id": 7, "scene_number": 1, "title": "פתיחה", "recommended_shot_count": 2}
                    ],
                },
                {"shots": [{"id": 21, "project_id": 7}, {"id": 22, "project_id": 7}]},
                {
                    "project": {"id": 7},
                    "scenes": [{"id": 11, "project_id": 7}],
                    "shots": [
                        {"id": 21, "project_id": 7, "scene_id": 11},
                        {"id": 22, "project_id": 7, "scene_id": 11},
                    ],
                },
            ]
            result = run_smoke(SmokeConfig(
                base_url="https://example.invalid",
                project_id=7,
                screenplay_file=screenplay,
                execute_import=True,
            ))

        self.assertTrue(result["import_executed"])
        self.assertEqual(result["processed_chunks"], 1)
        self.assertEqual(result["shot_maps_skipped"], 0)
        self.assertEqual(result["after"], {"scenes": 1, "shots": 2})
        paths = [call.args[1] for call in request_json.call_args_list]
        self.assertIn("/api/import-runs/process-next", paths)
        self.assertIn("/api/import-runs/persist", paths)
        self.assertIn("/api/scenes/11/shot-map", paths)
        self.assertNotIn("/api/scenes/import-script", paths)
        shot_map_call = next(call for call in request_json.call_args_list if call.args[1] == "/api/scenes/11/shot-map")
        self.assertFalse(shot_map_call.kwargs["payload"]["replace_existing"])

    @patch("scripts.deployment_smoke._request_json")
    def test_import_retry_skips_existing_shot_maps_without_replacement(self, request_json):
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            existing_snapshot = {
                "project": {"id": 7},
                "scenes": [{"id": 11, "project_id": 7}],
                "shots": [{"id": 21, "project_id": 7, "scene_id": 11}],
            }
            request_json.side_effect = [
                {"status": "ok"},
                {"status": "ready"},
                existing_snapshot,
                {
                    "screenplay_fingerprint": "f" * 64,
                    "next_chunk_index": 1,
                    "chunk_count": 1,
                    "completed": True,
                    "scenes": [{"scene_number": 1, "title": "פתיחה", "recommended_shot_count": 2}],
                },
                {
                    "persisted": False,
                    "idempotent_replay": True,
                    "scenes_created": 0,
                    "imported_scenes": [
                        {"id": 11, "project_id": 7, "scene_number": 1, "title": "פתיחה", "recommended_shot_count": 2}
                    ],
                },
                existing_snapshot,
            ]
            result = run_smoke(SmokeConfig(
                base_url="https://example.invalid",
                project_id=7,
                screenplay_file=screenplay,
                execute_import=True,
            ))

        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(result["shots_created"], 0)
        self.assertEqual(result["shot_maps_skipped"], 1)
        paths = [call.args[1] for call in request_json.call_args_list]
        self.assertNotIn("/api/scenes/11/shot-map", paths)


if __name__ == "__main__":
    unittest.main()
