import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services.seedance_provider import SeedanceProvider
from app.services.video_provider import VideoGenerationRequest, VideoProviderNotConfigured


class SeedanceProviderClientTests(unittest.TestCase):
    def setUp(self):
        self.original_key = settings.fal_api_key
        self.original_model = settings.fal_seedance_model
        self.original_fast_model = settings.fal_seedance_fast_model
        self.original_fal_key_env = os.environ.get("FAL_KEY")

        settings.fal_api_key = "test-key"
        settings.fal_seedance_model = "bytedance/seedance-2.0/image-to-video"
        settings.fal_seedance_fast_model = "bytedance/seedance-2.0/fast/image-to-video"
        self.request = VideoGenerationRequest(
            image_url="https://cdn.example/approved.png",
            prompt="subtle cinematic motion",
            duration_seconds=5,
            aspect_ratio="16:9",
        )

    def tearDown(self):
        settings.fal_api_key = self.original_key
        settings.fal_seedance_model = self.original_model
        settings.fal_seedance_fast_model = self.original_fast_model
        if self.original_fal_key_env is None:
            os.environ.pop("FAL_KEY", None)
        else:
            os.environ["FAL_KEY"] = self.original_fal_key_env

    def test_provider_requires_key(self):
        settings.fal_api_key = ""
        with self.assertRaises(VideoProviderNotConfigured):
            SeedanceProvider()

    def test_provider_maps_render_key_to_official_client_env(self):
        SeedanceProvider()
        self.assertEqual(os.environ.get("FAL_KEY"), "test-key")

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_generate_uses_official_submit_and_get(self, mock_submit):
        handler = MagicMock()
        handler.request_id = "req-1"
        handler.get.return_value = {
            "video": {"url": "https://cdn.example/video.mp4"}
        }
        mock_submit.return_value = handler

        result = SeedanceProvider().generate(self.request)

        self.assertEqual(result.url, "https://cdn.example/video.mp4")
        self.assertEqual(result.external_task_id, "req-1")
        self.assertEqual(result.provider, "seedance")
        self.assertEqual(result.model, settings.fal_seedance_model)
        mock_submit.assert_called_once()
        model, = mock_submit.call_args.args
        self.assertEqual(model, settings.fal_seedance_model)
        payload = mock_submit.call_args.kwargs["arguments"]
        self.assertEqual(payload["image_url"], self.request.image_url)
        self.assertIn("subtle cinematic motion", payload["prompt"])
        handler.get.assert_called_once_with()

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_generate_preserves_fast_model_selection(self, mock_submit):
        handler = MagicMock()
        handler.request_id = "req-fast"
        handler.get.return_value = {
            "video": {"url": "https://cdn.example/fast.mp4"}
        }
        mock_submit.return_value = handler
        request = VideoGenerationRequest(
            image_url=self.request.image_url,
            prompt=self.request.prompt,
            duration_seconds=5,
            model_profile="fast",
        )

        result = SeedanceProvider().generate(request)

        self.assertEqual(result.model, settings.fal_seedance_fast_model)
        self.assertEqual(mock_submit.call_args.args[0], settings.fal_seedance_fast_model)

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_generate_rejects_missing_request_id(self, mock_submit):
        mock_submit.return_value = SimpleNamespace(request_id="", get=lambda: {})

        with self.assertRaisesRegex(RuntimeError, "official client"):
            SeedanceProvider().generate(self.request)

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_provider_error_is_sanitized(self, mock_submit):
        handler = MagicMock()
        handler.request_id = "req-secret"
        handler.get.side_effect = RuntimeError(
            "signed_url=https://private.example/token=secret-provider-value"
        )
        mock_submit.return_value = handler

        with self.assertRaises(RuntimeError) as ctx:
            SeedanceProvider().generate(self.request)

        message = str(ctx.exception)
        self.assertEqual(message, "fal.ai generation failed via official client")
        self.assertNotIn("secret-provider-value", message)
        self.assertNotIn("private.example", message)

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_completed_response_must_contain_video_url(self, mock_submit):
        handler = MagicMock()
        handler.request_id = "req-no-video"
        handler.get.return_value = {"status": "ok"}
        mock_submit.return_value = handler

        with self.assertRaisesRegex(RuntimeError, "without a video URL"):
            SeedanceProvider().generate(self.request)


if __name__ == "__main__":
    unittest.main()
