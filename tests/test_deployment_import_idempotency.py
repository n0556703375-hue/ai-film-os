import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deployment_import_idempotency import verify_empty_project, verify_import_idempotency
from scripts.deployment_smoke import SmokeConfig, SmokeFailure


class DeploymentImportIdempotencyTests(unittest.TestCase):
    def _config(self, screenplay: Path, *, execute_import: bool = True) -> SmokeConfig:
        return SmokeConfig(
            base_url="https://example.invalid",
            project_id=7,
            screenplay_file=screenplay,
            execute_import=execute_import,
        )

    def test_requires_explicit_import_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            with self.assertRaisesRegex(SmokeFailure, "--execute-import"):
                verify_import_idempotency(self._config(screenplay, execute_import=False))

    @patch("scripts.deployment_import_idempotency._request_json")
    def test_empty_project_preflight_accepts_zero_counts(self, request_json):
        request_json.return_value = {
            "project": {"id": 7},
            "scenes": [],
            "shots": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            counts = verify_empty_project(self._config(screenplay))

        self.assertEqual(counts, {"scenes": 0, "shots": 0})

    @patch("scripts.deployment_import_idempotency._request_json")
    def test_empty_project_preflight_rejects_existing_data_before_import(self, request_json):
        request_json.return_value = {
            "project": {"id": 7},
            "scenes": [{"id": 1, "project_id": 7}],
            "shots": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            with self.assertRaisesRegex(SmokeFailure, "requires an empty isolated project"):
                verify_empty_project(self._config(screenplay))

    @patch("scripts.deployment_import_idempotency.verify_empty_project")
    @patch("scripts.deployment_import_idempotency.run_smoke")
    def test_accepts_unchanged_idempotent_replay(self, run_smoke, verify_empty_project):
        verify_empty_project.return_value = {"scenes": 0, "shots": 0}
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            run_smoke.side_effect = [
                {
                    "project_id": 7,
                    "import_executed": True,
                    "scenes_created": 2,
                    "shots_created": 6,
                    "after": {"scenes": 2, "shots": 6},
                },
                {
                    "project_id": 7,
                    "import_executed": True,
                    "idempotent_replay": True,
                    "scenes_created": 0,
                    "shots_created": 0,
                    "shot_maps_skipped": 2,
                    "before": {"scenes": 2, "shots": 6},
                    "after": {"scenes": 2, "shots": 6},
                },
            ]

            result = verify_import_idempotency(self._config(screenplay))

        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(result["counts"], {"scenes": 2, "shots": 6})
        self.assertEqual(result["second"]["shots_created"], 0)
        self.assertEqual(run_smoke.call_count, 2)
        verify_empty_project.assert_called_once()

    @patch("scripts.deployment_import_idempotency.verify_empty_project")
    @patch("scripts.deployment_import_idempotency.run_smoke")
    def test_rejects_second_run_that_is_not_idempotent(self, run_smoke, verify_empty_project):
        verify_empty_project.return_value = {"scenes": 0, "shots": 0}
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            run_smoke.side_effect = [
                {
                    "import_executed": True,
                    "scenes_created": 2,
                    "shots_created": 6,
                    "after": {"scenes": 2, "shots": 6},
                },
                {
                    "import_executed": True,
                    "idempotent_replay": False,
                    "shots_created": 1,
                    "before": {"scenes": 2, "shots": 6},
                    "after": {"scenes": 3, "shots": 7},
                },
            ]

            with self.assertRaisesRegex(SmokeFailure, "not reported as an idempotent replay"):
                verify_import_idempotency(self._config(screenplay))

    @patch("scripts.deployment_import_idempotency.verify_empty_project")
    @patch("scripts.deployment_import_idempotency.run_smoke")
    def test_rejects_count_growth_during_replay(self, run_smoke, verify_empty_project):
        verify_empty_project.return_value = {"scenes": 0, "shots": 0}
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            run_smoke.side_effect = [
                {
                    "import_executed": True,
                    "scenes_created": 2,
                    "shots_created": 6,
                    "after": {"scenes": 2, "shots": 6},
                },
                {
                    "import_executed": True,
                    "idempotent_replay": True,
                    "shots_created": 0,
                    "before": {"scenes": 2, "shots": 6},
                    "after": {"scenes": 2, "shots": 7},
                },
            ]

            with self.assertRaisesRegex(SmokeFailure, "totals changed"):
                verify_import_idempotency(self._config(screenplay))


if __name__ == "__main__":
    unittest.main()
