import unittest
from unittest.mock import patch

import httpx

from app.core.config import settings
from app.services.seedance_provider import SeedanceProvider
from app.services.video_provider import VideoGenerationRequest


class SeedanceProviderQueueTests(unittest.TestCase):
    def setUp(self):
        self.original_key = settings.fal_api_key
        self.original_base = settings.fal_api_base
        self.original_model = settings.fal_seedance_model
        settings.fal_api_key = "test-key"
        settings.fal_api_base = "https://queue.fal.run"
        settings.fal_seedance_model = "bytedance/seedance-2.0/image-to-video"
        self.request = VideoGenerationRequest(
            image_url="https://cdn.example/approved.png",
            prompt="subtle cinematic motion",
            duration_seconds=5,
        )

    def tearDown(self):
        settings.fal_api_key = self.original_key
        settings.fal_api_base = self.original_base
        settings.fal_seedance_model = self.original_model

    @patch("app.services.seedance_provider.time.sleep", return_value=None)
    @patch("app.services.seedance_provider.httpx.Client")
    def test_generate_uses_returned_status_url_and_documented_result_url(self, mock_client_cls, _sleep):
        client = mock_client_cls.return_value.__enter__.return_value
        status_url = "https://queue.fal.run/canonical/model/requests/req-1/status"
        response_url = "https://queue.fal.run/canonical/model/requests/req-1/response"
        result_url = "https://queue.fal.run/canonical/model/requests/req-1"
        client.post.return_value = httpx.Response(
            202,
            json={
                "request_id": "req-1",
                "status_url": status_url,
                "response_url": response_url,
            },
            request=httpx.Request("POST", "https://queue.fal.run/model"),
        )
        client.get.side_effect = [
            httpx.Response(
                200,
                json={"status": "COMPLETED", "request_id": "req-1"},
                request=httpx.Request("GET", status_url),
            ),
            httpx.Response(
                200,
                json={"video": {"url": "https://cdn.example/video.mp4"}},
                request=httpx.Request("GET", result_url),
            ),
        ]

        result = SeedanceProvider().generate(self.request)

        self.assertEqual(result.url, "https://cdn.example/video.mp4")
        self.assertEqual(result.external_task_id, "req-1")
        requested_urls = [call.args[0] for call in client.get.call_args_list]
        self.assertEqual(requested_urls, [status_url, result_url])

    @patch("app.services.seedance_provider.time.sleep", return_value=None)
    @patch("app.services.seedance_provider.httpx.Client")
    def test_generate_fallback_result_url_has_no_response_suffix(self, mock_client_cls, _sleep):
        client = mock_client_cls.return_value.__enter__.return_value
        model = settings.fal_seedance_model
        status_url = f"https://queue.fal.run/{model}/requests/req-2/status"
        result_url = f"https://queue.fal.run/{model}/requests/req-2"
        client.post.return_value = httpx.Response(
            202,
            json={"request_id": "req-2"},
            request=httpx.Request("POST", f"https://queue.fal.run/{model}"),
        )
        client.get.side_effect = [
            httpx.Response(
                200,
                json={"status": "COMPLETED"},
                request=httpx.Request("GET", status_url),
            ),
            httpx.Response(
                200,
                json={"video": {"url": "https://cdn.example/video-2.mp4"}},
                request=httpx.Request("GET", result_url),
            ),
        ]

        SeedanceProvider().generate(self.request)

        requested_urls = [call.args[0] for call in client.get.call_args_list]
        self.assertEqual(requested_urls, [status_url, result_url])

    @patch("app.services.seedance_provider.httpx.Client")
    def test_generate_rejects_provider_queue_url_on_untrusted_host(self, mock_client_cls):
        client = mock_client_cls.return_value.__enter__.return_value
        client.post.return_value = httpx.Response(
            202,
            json={
                "request_id": "req-3",
                "status_url": "https://evil.example/steal",
                "response_url": "https://queue.fal.run/model/requests/req-3/response",
            },
            request=httpx.Request("POST", "https://queue.fal.run/model"),
        )

        with self.assertRaisesRegex(RuntimeError, "invalid queue URL"):
            SeedanceProvider().generate(self.request)
        client.get.assert_not_called()

    @patch("app.services.seedance_provider.time.sleep", return_value=None)
    @patch("app.services.seedance_provider.httpx.Client")
    def test_result_fetch_error_does_not_expose_provider_body(self, mock_client_cls, _sleep):
        client = mock_client_cls.return_value.__enter__.return_value
        status_url = "https://queue.fal.run/model/requests/req-4/status"
        response_url = "https://queue.fal.run/model/requests/req-4/response"
        result_url = "https://queue.fal.run/model/requests/req-4"
        client.post.return_value = httpx.Response(
            202,
            json={
                "request_id": "req-4",
                "status_url": status_url,
                "response_url": response_url,
            },
            request=httpx.Request("POST", "https://queue.fal.run/model"),
        )
        secret_body = "signed_url=https://private.example/token=secret-provider-value"
        client.get.side_effect = [
            httpx.Response(
                200,
                json={"status": "COMPLETED"},
                request=httpx.Request("GET", status_url),
            ),
            httpx.Response(
                422,
                text=secret_body,
                request=httpx.Request("GET", result_url),
            ),
        ]

        with self.assertRaises(RuntimeError) as ctx:
            SeedanceProvider().generate(self.request)

        message = str(ctx.exception)
        self.assertIn("HTTP 422", message)
        self.assertNotIn(secret_body, message)
        self.assertNotIn("secret-provider-value", message)


if __name__ == "__main__":
    unittest.main()
