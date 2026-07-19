import unittest
from unittest.mock import patch

import httpx

from app.core.config import settings
from app.services.magnific_connection import check_magnific_connection


class _FakeClient:
    def __init__(self, response=None, error=None, **kwargs):
        self.response = response
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, headers=None):
        if self.error:
            raise self.error
        return self.response


class MagnificConnectionTests(unittest.TestCase):
    def setUp(self):
        self.original_key = settings.magnific_api_key
        self.original_base = settings.magnific_api_base
        settings.magnific_api_base = "https://api.magnific.test"

    def tearDown(self):
        settings.magnific_api_key = self.original_key
        settings.magnific_api_base = self.original_base

    def test_missing_key_is_not_configured(self):
        settings.magnific_api_key = ""

        result = check_magnific_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "not_configured")
        self.assertIsNone(result["http_status"])

    def test_not_found_probe_confirms_valid_connection(self):
        settings.magnific_api_key = "test-key"
        response = httpx.Response(404, request=httpx.Request("GET", "https://api.magnific.test"))

        with patch(
            "app.services.magnific_connection.httpx.Client",
            return_value=_FakeClient(response=response),
        ):
            result = check_magnific_connection()

        self.assertTrue(result["connected"])
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["http_status"], 404)
        self.assertIsInstance(result["latency_ms"], int)

    def test_unauthorized_response_marks_key_invalid(self):
        settings.magnific_api_key = "bad-key"
        response = httpx.Response(401, request=httpx.Request("GET", "https://api.magnific.test"))

        with patch(
            "app.services.magnific_connection.httpx.Client",
            return_value=_FakeClient(response=response),
        ):
            result = check_magnific_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "invalid_key")
        self.assertEqual(result["http_status"], 401)

    def test_timeout_is_reported_without_exception(self):
        settings.magnific_api_key = "test-key"
        request = httpx.Request("GET", "https://api.magnific.test")

        with patch(
            "app.services.magnific_connection.httpx.Client",
            return_value=_FakeClient(error=httpx.ReadTimeout("timeout", request=request)),
        ):
            result = check_magnific_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "timeout")

    def test_unexpected_provider_status_is_reported(self):
        settings.magnific_api_key = "test-key"
        response = httpx.Response(500, request=httpx.Request("GET", "https://api.magnific.test"))

        with patch(
            "app.services.magnific_connection.httpx.Client",
            return_value=_FakeClient(response=response),
        ):
            result = check_magnific_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "provider_error")
        self.assertEqual(result["http_status"], 500)


if __name__ == "__main__":
    unittest.main()
