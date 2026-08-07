import io
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from scripts.deployment_smoke import RetryableChunkFailure, SmokeConfig, SmokeFailure, _request_json


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
    def test_retryable_502_raises_retryable_chunk_failure(self, urlopen):
        retryable_body = b'{"detail":{"message":"transient","code":"screenplay_chunk_failure","failure_category":"rate_limit","retryable":true}}'
        urlopen.side_effect = HTTPError(
            url="https://example.invalid/api/import-runs/process-next",
            code=502,
            msg="Bad Gateway",
            hdrs={"Content-Type": "application/json"},
            fp=io.BytesIO(retryable_body),
        )

        with self.assertRaises(RetryableChunkFailure) as captured:
            _request_json(
                self.config,
                "/api/import-runs/process-next",
                method="POST",
                payload={"project_id": 7},
            )

        message = str(captured.exception)
        self.assertIn("POST /api/import-runs/process-next", message)
        self.assertIn("retryable HTTP 502", message)
        self.assertIn("rate_limit", message)
        self.assertEqual(captured.exception.category, "rate_limit")
        self.assertNotIn("transient", message)
        self.assertNotIn("screenplay_chunk_failure", message)

    @patch("scripts.deployment_smoke.urlopen")
    def test_unknown_failure_category_is_not_echoed(self, urlopen):
        retryable_body = b'{"detail":{"failure_category":"SECRET_SENTINEL","retryable":true}}'
        urlopen.side_effect = HTTPError(
            url="https://example.invalid/api/import-runs/process-next",
            code=502,
            msg="Bad Gateway",
            hdrs={"Content-Type": "application/json"},
            fp=io.BytesIO(retryable_body),
        )

        with self.assertRaises(RetryableChunkFailure) as captured:
            _request_json(
                self.config,
                "/api/import-runs/process-next",
                method="POST",
                payload={"project_id": 7},
            )

        self.assertEqual(captured.exception.category, "unknown")
        self.assertNotIn("SECRET_SENTINEL", str(captured.exception))

    @patch("scripts.deployment_smoke.urlopen")
    def test_non_retryable_failure_reports_only_safe_category(self, urlopen):
        body = b'{"detail":{"message":"SECRET_SENTINEL","failure_category":"authentication","retryable":false}}'
        urlopen.side_effect = HTTPError(
            url="https://example.invalid/api/import-runs/process-next",
            code=502,
            msg="Bad Gateway",
            hdrs={"Content-Type": "application/json"},
            fp=io.BytesIO(body),
        )

        with self.assertRaises(SmokeFailure) as captured:
            _request_json(
                self.config,
                "/api/import-runs/process-next",
                method="POST",
                payload={"project_id": 7},
            )

        self.assertNotIsInstance(captured.exception, RetryableChunkFailure)
        self.assertIn("authentication", str(captured.exception))
        self.assertNotIn("SECRET_SENTINEL", str(captured.exception))

    @patch("scripts.deployment_smoke.urlopen")
    def test_retryable_chunk_failure_is_subclass_of_smoke_failure(self, urlopen):
        retryable_body = b'{"detail":{"retryable":true}}'
        urlopen.side_effect = HTTPError(
            url="https://example.invalid/api/import-runs/process-next",
            code=502,
            msg="Bad Gateway",
            hdrs={"Content-Type": "application/json"},
            fp=io.BytesIO(retryable_body),
        )

        with self.assertRaises(SmokeFailure):
            _request_json(
                self.config,
                "/api/import-runs/process-next",
                method="POST",
                payload={"project_id": 7},
            )

    @patch("scripts.deployment_smoke.urlopen")
    def test_non_retryable_502_raises_plain_smoke_failure(self, urlopen):
        non_retryable_body = b'{"detail":{"message":"permanent failure","retryable":false}}'
        urlopen.side_effect = HTTPError(
            url="https://example.invalid/api/import-runs/process-next",
            code=502,
            msg="Bad Gateway",
            hdrs={"Content-Type": "application/json"},
            fp=io.BytesIO(non_retryable_body),
        )

        with self.assertRaises(SmokeFailure) as captured:
            _request_json(
                self.config,
                "/api/import-runs/process-next",
                method="POST",
                payload={"project_id": 7},
            )

        self.assertNotIsInstance(captured.exception, RetryableChunkFailure)

    @patch("scripts.deployment_smoke.urlopen")
    def test_non_boolean_retryable_values_are_not_retryable(self, urlopen):
        for encoded_value in ('"true"', '"false"', "1", "null"):
            with self.subTest(retryable=encoded_value):
                body = ('{"detail":{"retryable":' + encoded_value + "}}").encode("utf-8")
                urlopen.side_effect = HTTPError(
                    url="https://example.invalid/api/import-runs/process-next",
                    code=502,
                    msg="Bad Gateway",
                    hdrs={"Content-Type": "application/json"},
                    fp=io.BytesIO(body),
                )

                with self.assertRaises(SmokeFailure) as captured:
                    _request_json(
                        self.config,
                        "/api/import-runs/process-next",
                        method="POST",
                        payload={"project_id": 7},
                    )

                self.assertNotIsInstance(captured.exception, RetryableChunkFailure)

    @patch("scripts.deployment_smoke.urlopen")
    def test_502_with_unparseable_body_raises_plain_smoke_failure(self, urlopen):
        urlopen.side_effect = HTTPError(
            url="https://example.invalid/api/import-runs/process-next",
            code=502,
            msg="Bad Gateway",
            hdrs={"Content-Type": "text/html"},
            fp=io.BytesIO(b"<html>Bad Gateway</html>"),
        )

        with self.assertRaises(SmokeFailure) as captured:
            _request_json(
                self.config,
                "/api/import-runs/process-next",
                method="POST",
                payload={"project_id": 7},
            )

        self.assertNotIsInstance(captured.exception, RetryableChunkFailure)

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
