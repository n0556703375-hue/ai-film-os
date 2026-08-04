import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deployment_import_idempotency import verify_import_idempotency
from scripts.deployment_smoke import SmokeConfig, SmokeFailure


class DeploymentImportRequiresContentTests(unittest.TestCase):
    def _config(self, screenplay: Path) -> SmokeConfig:
        return SmokeConfig(
            base_url="https://example.invalid",
            project_id=7,
            screenplay_file=screenplay,
            execute_import=True,
        )

    @patch("scripts.deployment_import_idempotency.verify_empty_project")
    @patch("scripts.deployment_import_idempotency.run_smoke")
    def test_rejects_zero_content_false_positive(self, run_smoke, verify_empty_project):
        verify_empty_project.return_value = {"scenes": 0, "shots": 0}
        run_smoke.side_effect = [
            {
                "import_executed": True,
                "scenes_created": 0,
                "shots_created": 0,
                "after": {"scenes": 0, "shots": 0},
            },
            {
                "import_executed": True,
                "idempotent_replay": True,
                "scenes_created": 0,
                "shots_created": 0,
                "before": {"scenes": 0, "shots": 0},
                "after": {"scenes": 0, "shots": 0},
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            with self.assertRaisesRegex(SmokeFailure, "did not create both scenes and shots"):
                verify_import_idempotency(self._config(screenplay))

    @patch("scripts.deployment_import_idempotency.verify_empty_project")
    @patch("scripts.deployment_import_idempotency.run_smoke")
    def test_rejects_missing_persisted_content_even_when_created_counts_are_positive(
        self, run_smoke, verify_empty_project
    ):
        verify_empty_project.return_value = {"scenes": 0, "shots": 0}
        run_smoke.side_effect = [
            {
                "import_executed": True,
                "scenes_created": 2,
                "shots_created": 6,
                "after": {"scenes": 0, "shots": 0},
            },
            {
                "import_executed": True,
                "idempotent_replay": True,
                "scenes_created": 0,
                "shots_created": 0,
                "before": {"scenes": 0, "shots": 0},
                "after": {"scenes": 0, "shots": 0},
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            with self.assertRaisesRegex(SmokeFailure, "left no persisted scenes or shots"):
                verify_import_idempotency(self._config(screenplay))


if __name__ == "__main__":
    unittest.main()
