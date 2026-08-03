import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deployment_smoke import SmokeFailure
from scripts.deployment_smoke_idempotency import run_idempotency_smoke


class DeploymentSmokeIdempotencyCommandTests(unittest.TestCase):
    def _argv(self, screenplay: Path) -> list[str]:
        return [
            "--base-url",
            "https://example.invalid",
            "--project-id",
            "7",
            "--screenplay-file",
            str(screenplay),
            "--execute-import",
        ]

    @patch("scripts.deployment_smoke_idempotency.run_smoke")
    def test_accepts_stable_second_idempotent_run(self, run_smoke):
        run_smoke.side_effect = [
            {
                "project_id": 7,
                "after": {"scenes": 1, "shots": 2},
                "idempotent_replay": False,
                "shots_created": 2,
            },
            {
                "project_id": 7,
                "before": {"scenes": 1, "shots": 2},
                "after": {"scenes": 1, "shots": 2},
                "idempotent_replay": True,
                "shots_created": 0,
                "shot_maps_skipped": 1,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            result = run_idempotency_smoke(self._argv(screenplay))

        self.assertTrue(result["ok"])
        self.assertTrue(result["second"]["idempotent_replay"])
        self.assertEqual(result["second"]["shots_created"], 0)
        self.assertEqual(run_smoke.call_count, 2)

    @patch("scripts.deployment_smoke_idempotency.run_smoke")
    def test_rejects_count_changes_on_second_run(self, run_smoke):
        run_smoke.side_effect = [
            {"after": {"scenes": 1, "shots": 2}, "idempotent_replay": False, "shots_created": 2},
            {
                "before": {"scenes": 1, "shots": 2},
                "after": {"scenes": 2, "shots": 3},
                "idempotent_replay": True,
                "shots_created": 1,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            with self.assertRaisesRegex(SmokeFailure, "counts changed"):
                run_idempotency_smoke(self._argv(screenplay))

    @patch("scripts.deployment_smoke_idempotency.run_smoke")
    def test_rejects_second_run_not_marked_idempotent(self, run_smoke):
        stable = {"scenes": 1, "shots": 2}
        run_smoke.side_effect = [
            {"after": stable, "idempotent_replay": False, "shots_created": 2},
            {
                "before": stable,
                "after": stable,
                "idempotent_replay": False,
                "shots_created": 0,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            screenplay = Path(directory) / "screenplay.txt"
            screenplay.write_text("א" * 80, encoding="utf-8")
            with self.assertRaisesRegex(SmokeFailure, "not reported as an idempotent replay"):
                run_idempotency_smoke(self._argv(screenplay))


if __name__ == "__main__":
    unittest.main()
