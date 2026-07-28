import io
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from scripts.deployment_smoke import SmokeConfig, SmokeFailure, _request_json


class DeploymentSmokeHttpFailureTests(unittest.TestCase):
    def setUp(self):
        self.config = SmokeConfig(
            base_url="https://example.invalid",
            project_id=7,
        )

    @patch("scripts.deployment_smoke.urlopen")
    def test_http_error_reports_status_and_stage_without_leaking_json_body(self, urlopen):
        secret_body = b'{"detail":{"message":"provider secret payload","code":"screenplay_chunk_failure"}}'
        urlopen.side_effect = HTTPError(
            url="https://example.invalid/api/import-runs/process-next",
            code=502,
            msg="Bad Gateway",
            hdrs={"Content-Type": "application/json"},
            fp=io.BytesIO(secret_body),
        )

        with self.assertRaises(SmokeFailure) as captured:
            _request_json(
                self.config,
                "/api/import-runs/process-next",
                method="POST",
                payload={"project_id": 7},
            )

        message = str(captured.exception)
        self.assertIn("POST /api/import-runs/process-next", message)
        self.assertIn("HTTP 502", message)
        self.assertNotIn("provider secret payload", message)
        self.assertNotIn("screenplay_chunk_failure", message)
        self.assertNotIn("example.invalid", message)

    @patch("scripts.deployment_smoke.urlopen")
    def test_html_proxy_error_is_never_echoed(self, urlopen):
        html = b"<html><body>upstream token=do-not-print</body></html>"
        urlopen.side_effect = HTTPError(
            url="https://example.invalid/api/import-runs/process-next",
            code=504,
            msg="Gateway Timeout",
            hdrs={"Content-Type": "text/html"},
            fp=io.BytesIO(html),
        )

        with self.assertRaises(SmokeFailure) as captured:
            _request_json(self.config, "/api/import-runs/process-next", method="POST")

        message = str(captured.exception)
        self.assertIn("HTTP 504", message)
        self.assertNotIn("upstream token", message)
        self.assertNotIn("<html>", message)

    @patch("scripts.deployment_smoke.urlopen")
    def test_network_failure_does_not_echo_low_level_connection_details(self, urlopen):
        urlopen.side_effect = URLError("connection failed with credential=do-not-print")

        with self.assertRaises(SmokeFailure) as captured:
            _request_json(self.config, "/health")

        message = str(captured.exception)
        self.assertEqual(message, "GET /health could not reach the deployed service")
        self.assertNotIn("credential", message)


if __name__ == "__main__":
    unittest.main()
