import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.health import health
from app.core.version import APP_VERSION
from scripts.deployment_smoke import (
    SmokeConfig,
    SmokeFailure,
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
        from app.main import app

        paths = {
            route.path
            for route in app.routes
            if isinstance(getattr(route, "path", None), str)
        }
        self.assertIn("/health", paths)
        self.assertIn("/ready", paths)
        self.assertIn("/api/scenes/import-script", paths)
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

    def test_import_payload_never_replaces_existing_records(self):
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
        self.assertFalse(payload["replace_existing"])
        self.assertTrue(payload["generate_shot_maps"])

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

    @patch("scripts.deployment_smoke._request_json")
    def test_default_run_is_read_only(self, request_json):
        request_json.side_effect = [
            {"status": "ok"},
            {"status": "ready"},
            {
                "project": {"id": 7},
                "scenes": [{"id": 1, "project_id": 7}],
                "shots": [{"id": 2, "project_id": 7}],
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
    def test_import_run_verifies_non_replacing_persistence(self, request_json):
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            request_json.side_effect = [
                {"status": "ok"},
                {"status": "ready"},
                {"project": {"id": 7}, "scenes": [], "shots": []},
                {
                    "completed_stages": ["screenplay_breakdown", "scene_persistence", "shot_map_generation"],
                    "scenes_created": 1,
                    "shots_created": 2,
                },
                {
                    "project": {"id": 7},
                    "scenes": [{"id": 1, "project_id": 7}],
                    "shots": [
                        {"id": 2, "project_id": 7},
                        {"id": 3, "project_id": 7},
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
        self.assertEqual(result["after"], {"scenes": 1, "shots": 2})
        import_call = request_json.call_args_list[3]
        self.assertEqual(import_call.kwargs["method"], "POST")
        self.assertFalse(import_call.kwargs["payload"]["replace_existing"])


if __name__ == "__main__":
    unittest.main()
