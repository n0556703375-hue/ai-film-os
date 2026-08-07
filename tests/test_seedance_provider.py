import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fal_client

from app.core.config import settings
from app.services.seedance_provider import (
    SeedanceErrorCategory,
    SeedanceProvider,
    SeedanceProviderError,
)
from app.services.video_provider import VideoGenerationRequest, VideoProviderNotConfigured


class SeedanceProviderTestBase(unittest.TestCase):
    def setUp(self):
        self.original_key = settings.fal_api_key
        self.original_model = settings.fal_seedance_model
        self.original_fast_model = settings.fal_seedance_fast_model
        self.original_fal_key_env = os.environ.get("FAL_KEY")
        self.original_render_external_url = os.environ.get("RENDER_EXTERNAL_URL")
        self.original_public_base_url = os.environ.get("PUBLIC_BASE_URL")

        settings.fal_api_key = "test-key"
        settings.fal_seedance_model = "bytedance/seedance-2.0/image-to-video"
        settings.fal_seedance_fast_model = "bytedance/seedance-2.0/fast/image-to-video"
        os.environ.pop("PUBLIC_BASE_URL", None)
        os.environ.pop("RENDER_EXTERNAL_URL", None)

        # Preflight reachability (a real bounded HTTP fetch) is covered on
        # its own in tests/test_public_media_url.py; provider tests stay
        # hermetic by assuming any normalized URL preflights clean unless a
        # specific test overrides this.
        preflight_patcher = patch("app.services.seedance_provider.preflight_check_public_image")
        preflight_patcher.start()
        self.addCleanup(preflight_patcher.stop)

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
        if self.original_render_external_url is None:
            os.environ.pop("RENDER_EXTERNAL_URL", None)
        else:
            os.environ["RENDER_EXTERNAL_URL"] = self.original_render_external_url
        if self.original_public_base_url is None:
            os.environ.pop("PUBLIC_BASE_URL", None)
        else:
            os.environ["PUBLIC_BASE_URL"] = self.original_public_base_url


class SeedanceProviderConfigTests(SeedanceProviderTestBase):
    def test_provider_requires_key(self):
        settings.fal_api_key = ""
        with self.assertRaises(VideoProviderNotConfigured):
            SeedanceProvider()

    def test_provider_maps_render_key_to_official_client_env(self):
        SeedanceProvider()
        self.assertEqual(os.environ.get("FAL_KEY"), "test-key")


class SeedanceSubmitTests(SeedanceProviderTestBase):
    """submit() must only enqueue the request — never block on completion."""

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_submit_uses_current_seedance_schema(self, mock_submit):
        mock_submit.return_value = SimpleNamespace(request_id="req-1")

        task_id = SeedanceProvider().submit(self.request)

        self.assertEqual(task_id, f"{settings.fal_seedance_model}::req-1")
        model, = mock_submit.call_args.args
        self.assertEqual(model, settings.fal_seedance_model)
        payload = mock_submit.call_args.kwargs["arguments"]
        self.assertEqual(payload["image_url"], self.request.image_url)
        self.assertIn("subtle cinematic motion", payload["prompt"])
        self.assertEqual(payload["duration"], "5")
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["aspect_ratio"], "16:9")
        self.assertFalse(payload["generate_audio"])
        self.assertNotIn("height", payload)
        self.assertNotIn("width", payload)
        # submit() must never call the blocking .get()/.iter_events() path.
        self.assertFalse(hasattr(mock_submit.return_value, "get") and mock_submit.return_value.get.called)

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_relative_generated_image_uses_render_public_url(self, mock_submit):
        os.environ["RENDER_EXTERNAL_URL"] = "https://ai-film-os.onrender.com"
        mock_submit.return_value = SimpleNamespace(request_id="req-relative")
        request = VideoGenerationRequest(
            image_url="/generated/shot-1.png",
            prompt=self.request.prompt,
            duration_seconds=5,
            aspect_ratio="16:9",
        )

        SeedanceProvider().submit(request)

        payload = mock_submit.call_args.kwargs["arguments"]
        self.assertEqual(
            payload["image_url"],
            "https://ai-film-os.onrender.com/generated/shot-1.png",
        )

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_relative_image_without_public_base_is_rejected_before_submit(self, mock_submit):
        request = VideoGenerationRequest(
            image_url="/generated/shot-1.png",
            prompt=self.request.prompt,
            duration_seconds=5,
        )

        with self.assertRaises(SeedanceProviderError) as ctx:
            SeedanceProvider().submit(request)
        self.assertEqual(ctx.exception.category, SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE)
        mock_submit.assert_not_called()

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_local_or_insecure_image_url_is_rejected_before_submit(self, mock_submit):
        for image_url in (
            "http://example.com/image.png",
            "https://localhost/image.png",
            "https://127.0.0.1/image.png",
        ):
            with self.subTest(image_url=image_url):
                request = VideoGenerationRequest(
                    image_url=image_url,
                    prompt=self.request.prompt,
                    duration_seconds=5,
                )
                with self.assertRaises(SeedanceProviderError) as ctx:
                    SeedanceProvider().submit(request)
                self.assertEqual(
                    ctx.exception.category, SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE
                )
        mock_submit.assert_not_called()

    @patch("app.services.seedance_provider.preflight_check_public_image")
    @patch("app.services.seedance_provider.fal_client.submit")
    def test_unreachable_source_image_is_rejected_before_submit(self, mock_submit, mock_preflight):
        from app.services.public_media_url import PublicMediaUrlError

        mock_preflight.side_effect = PublicMediaUrlError(PublicMediaUrlError.UNREACHABLE)

        with self.assertRaises(SeedanceProviderError) as ctx:
            SeedanceProvider().submit(self.request)
        self.assertEqual(ctx.exception.category, SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE)
        mock_submit.assert_not_called()

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_duration_is_clamped_to_supported_seedance_range(self, mock_submit):
        mock_submit.return_value = SimpleNamespace(request_id="req-duration")

        short = VideoGenerationRequest(
            image_url=self.request.image_url,
            prompt=self.request.prompt,
            duration_seconds=2,
            aspect_ratio="16:9",
        )
        SeedanceProvider().submit(short)
        self.assertEqual(mock_submit.call_args.kwargs["arguments"]["duration"], "4")

        long = VideoGenerationRequest(
            image_url=self.request.image_url,
            prompt=self.request.prompt,
            duration_seconds=30,
            aspect_ratio="16:9",
        )
        SeedanceProvider().submit(long)
        self.assertEqual(mock_submit.call_args.kwargs["arguments"]["duration"], "15")

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_invalid_aspect_ratio_falls_back_to_auto(self, mock_submit):
        mock_submit.return_value = SimpleNamespace(request_id="req-ratio")
        request = VideoGenerationRequest(
            image_url=self.request.image_url,
            prompt=self.request.prompt,
            duration_seconds=5,
            aspect_ratio="1920:1080",
        )

        SeedanceProvider().submit(request)

        self.assertEqual(mock_submit.call_args.kwargs["arguments"]["aspect_ratio"], "auto")

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_submit_preserves_fast_model_selection(self, mock_submit):
        mock_submit.return_value = SimpleNamespace(request_id="req-fast")
        request = VideoGenerationRequest(
            image_url=self.request.image_url,
            prompt=self.request.prompt,
            duration_seconds=5,
            model_profile="fast",
        )

        task_id = SeedanceProvider().submit(request)

        self.assertEqual(task_id, f"{settings.fal_seedance_fast_model}::req-fast")
        self.assertEqual(mock_submit.call_args.args[0], settings.fal_seedance_fast_model)

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_submit_rejects_missing_request_id(self, mock_submit):
        mock_submit.return_value = SimpleNamespace(request_id="")

        with self.assertRaises(SeedanceProviderError) as ctx:
            SeedanceProvider().submit(self.request)
        self.assertEqual(ctx.exception.category, SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE)

    @patch("app.services.seedance_provider.fal_client.submit")
    def test_submit_error_is_sanitized(self, mock_submit):
        mock_submit.side_effect = RuntimeError(
            "signed_url=https://private.example/token=secret-provider-value"
        )

        with self.assertRaises(SeedanceProviderError) as ctx:
            SeedanceProvider().submit(self.request)

        message = str(ctx.exception)
        self.assertNotIn("secret-provider-value", message)
        self.assertNotIn("private.example", message)
        self.assertEqual(ctx.exception.category, SeedanceErrorCategory.PROVIDER_FAILED)


class SeedanceCheckTaskTests(SeedanceProviderTestBase):
    """check_task() must be a single non-blocking status probe, resumable
    purely from the opaque task id — it never re-submits."""

    def _task_id(self, request_id="req-1", model=None):
        return f"{model or settings.fal_seedance_model}::{request_id}"

    @patch("app.services.seedance_provider.fal_client.status")
    def test_pending_status_reports_pending_without_touching_result(self, mock_status):
        mock_status.return_value = fal_client.InProgress(logs=None)

        status = SeedanceProvider().check_task(self._task_id())

        self.assertEqual(status["status"], "pending")
        mock_status.assert_called_once_with(settings.fal_seedance_model, "req-1", with_logs=False)

    @patch("app.services.seedance_provider.fal_client.result")
    @patch("app.services.seedance_provider.fal_client.status")
    def test_completed_status_fetches_result_and_extracts_video_url(self, mock_status, mock_result):
        mock_status.return_value = fal_client.Completed(logs=None, metrics={}, error=None, error_type=None)
        mock_result.return_value = {"video": {"url": "https://cdn.example/video.mp4"}}

        status = SeedanceProvider().check_task(self._task_id())

        self.assertEqual(status, {"status": "succeed", "url": "https://cdn.example/video.mp4", "reason": ""})
        mock_result.assert_called_once_with(settings.fal_seedance_model, "req-1")

    @patch("app.services.seedance_provider.fal_client.status")
    def test_check_task_never_resubmits(self, mock_status):
        mock_status.return_value = fal_client.InProgress(logs=None)
        with patch("app.services.seedance_provider.fal_client.submit") as mock_submit:
            SeedanceProvider().check_task(self._task_id())
            mock_submit.assert_not_called()

    @patch("app.services.seedance_provider.fal_client.result")
    @patch("app.services.seedance_provider.fal_client.status")
    def test_completed_without_video_url_is_failed_invalid_response(self, mock_status, mock_result):
        mock_status.return_value = fal_client.Completed(logs=None, metrics={}, error=None, error_type=None)
        mock_result.return_value = {"status": "ok"}

        status = SeedanceProvider().check_task(self._task_id())

        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["reason"], SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE)

    @patch("app.services.seedance_provider.fal_client.status")
    def test_completed_with_moderation_error_type_is_categorized(self, mock_status):
        mock_status.return_value = fal_client.Completed(
            logs=None, metrics={}, error="rejected", error_type="content_policy_violation"
        )

        status = SeedanceProvider().check_task(self._task_id())

        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["reason"], SeedanceErrorCategory.MODERATION_REJECTED)

    def test_check_task_rejects_malformed_task_id(self):
        with self.assertRaises(SeedanceProviderError) as ctx:
            SeedanceProvider().check_task("not-a-valid-task-id")
        self.assertEqual(ctx.exception.category, SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE)

    @patch("app.services.seedance_provider.fal_client.status")
    def test_http_401_is_authentication_failed_and_never_leaks_body(self, mock_status):
        response = MagicMock()
        mock_status.side_effect = fal_client.FalClientHTTPError(
            "unauthorized: key=sk-secret-value", 401, {}, response=response, error_type=None
        )

        status = SeedanceProvider().check_task(self._task_id())

        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["reason"], SeedanceErrorCategory.AUTHENTICATION_FAILED)

    @patch("app.services.seedance_provider.fal_client.status")
    def test_http_429_is_rate_limited(self, mock_status):
        response = MagicMock()
        mock_status.side_effect = fal_client.FalClientHTTPError(
            "too many requests", 429, {}, response=response, error_type=None
        )

        status = SeedanceProvider().check_task(self._task_id())

        self.assertEqual(status["reason"], SeedanceErrorCategory.RATE_LIMITED)

    @patch("app.services.seedance_provider.fal_client.status")
    def test_http_500_is_provider_failed(self, mock_status):
        response = MagicMock()
        mock_status.side_effect = fal_client.FalClientHTTPError(
            "internal error", 500, {}, response=response, error_type=None
        )

        status = SeedanceProvider().check_task(self._task_id())

        self.assertEqual(status["reason"], SeedanceErrorCategory.PROVIDER_FAILED)

    @patch("app.services.seedance_provider.fal_client.status")
    def test_timeout_error_is_provider_timeout(self, mock_status):
        mock_status.side_effect = fal_client.FalClientTimeoutError(30.0, request_id="req-1")

        status = SeedanceProvider().check_task(self._task_id())

        self.assertEqual(status["reason"], SeedanceErrorCategory.PROVIDER_TIMEOUT)


class SeedanceErrorCategoryRetryabilityTests(unittest.TestCase):
    def test_non_retryable_categories_are_marked_not_retryable(self):
        for category in (
            SeedanceErrorCategory.AUTHENTICATION_FAILED,
            SeedanceErrorCategory.INVALID_INPUT,
            SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE,
            SeedanceErrorCategory.INSUFFICIENT_CREDITS,
            SeedanceErrorCategory.MODERATION_REJECTED,
            SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE,
        ):
            self.assertFalse(SeedanceProviderError(category).retryable)

    def test_transient_categories_are_marked_retryable(self):
        for category in (
            SeedanceErrorCategory.RATE_LIMITED,
            SeedanceErrorCategory.PROVIDER_TIMEOUT,
            SeedanceErrorCategory.PROVIDER_FAILED,
        ):
            self.assertTrue(SeedanceProviderError(category).retryable)

    def test_error_message_never_contains_status_code_label_confusion(self):
        error = SeedanceProviderError(SeedanceErrorCategory.RATE_LIMITED, status_code=429)
        self.assertIn("rate_limited", str(error))
        self.assertIn("429", str(error))


if __name__ == "__main__":
    unittest.main()
