import unittest

from scripts.deployment_smoke import SmokeConfig, SmokeFailure, run_smoke
from unittest.mock import patch


class DeploymentSmokeProjectGuardTests(unittest.TestCase):
    @patch("scripts.deployment_smoke._request_json")
    def test_run_rejects_snapshot_for_a_different_project(self, request_json):
        request_json.side_effect = [
            {"status": "ok"},
            {"status": "ready"},
            {
                "project": {"id": 8},
                "scenes": [{"id": 1, "project_id": 8}],
                "shots": [],
            },
        ]

        with self.assertRaisesRegex(SmokeFailure, "unexpected project"):
            run_smoke(
                SmokeConfig(
                    base_url="https://example.invalid",
                    project_id=7,
                )
            )


if __name__ == "__main__":
    unittest.main()
