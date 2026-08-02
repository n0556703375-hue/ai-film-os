import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts.deployment_smoke import SmokeConfig, SmokeFailure, _request_json


class DeploymentSmokeRedactionTests(unittest.TestCase):
    @patch("scripts.deployment_smoke.urlopen")
    def test_http_failure_does_not_expose_response_body_or_base_url(self, urlopen):
        urlopen.side_effect = HTTPError(
            url="https://secret-host.invalid/health?token=do-not-print",
            code=502,
            msg="upstream failed",
            hdrs=None,
            fp=None,
        )
        config = SmokeConfig(
            base_url="https://secret-host.invalid?token=do-not-print",
            project_id=7,
        )

        with self.assertRaises(SmokeFailure) as caught:
            _request_json(config, "/health")

        message = str(caught.exception)
        self.assertEqual(message, "GET /health returned HTTP 502")
        self.assertNotIn("secret-host", message)
        self.assertNotIn("do-not-print", message)

    @patch("scripts.deployment_smoke.urlopen")
    def test_network_failure_does_not_expose_transport_reason(self, urlopen):
        urlopen.side_effect = URLError("credential-like transport detail")
        config = SmokeConfig(
            base_url="https://example.invalid",
            project_id=7,
        )

        with self.assertRaises(SmokeFailure) as caught:
            _request_json(config, "/ready")

        message = str(caught.exception)
        self.assertEqual(message, "GET /ready could not reach the deployed service")
        self.assertNotIn("credential-like", message)


if __name__ == "__main__":
    unittest.main()
