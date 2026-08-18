"""Coverage for app.services.video_identity_vision.evaluate_shot_video_identity
— confirms it downloads the video, extracts a frame, and then delegates
entirely to the same evaluate_shot_identity() the image flow uses (same
locked-character gathering, same adapter, same result shape).
"""

import unittest
from unittest.mock import Mock, patch

import httpx

from app.services.video_identity_vision import (
    VideoIdentityEvaluationError,
    evaluate_shot_video_identity,
)

_REAL_HTTPX_CLIENT = httpx.Client


def _mock_transport(handler):
    return httpx.MockTransport(handler)


_LOCKED_SHOT = {
    "assets": [
        {
            "id": 1, "name": "גיבורה", "asset_type": "דמות", "lock_status": "locked",
            "reference_images": ["https://example.com/ref.png"],
        }
    ]
}


class VideoIdentityVisionTests(unittest.TestCase):
    def _patch_client(self, handler):
        return unittest.mock.patch(
            "app.services.video_identity_vision.httpx.Client",
            lambda **kwargs: _REAL_HTTPX_CLIENT(transport=_mock_transport(handler), **kwargs),
        )

    def test_empty_url_raises(self):
        with self.assertRaises(ValueError):
            evaluate_shot_video_identity(shot=_LOCKED_SHOT, candidate_video_url="", adapter=Mock())

    def test_download_failure_raises_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        with self._patch_client(handler):
            with self.assertRaises(VideoIdentityEvaluationError) as ctx:
                evaluate_shot_video_identity(
                    shot=_LOCKED_SHOT, candidate_video_url="https://example.com/v.mp4", adapter=Mock(),
                )
        self.assertEqual(ctx.exception.reason, VideoIdentityEvaluationError.UNREACHABLE)

    def test_oversized_video_raises_too_large(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"\x00" * (1024 * 1024))

        with self._patch_client(handler), patch(
            "app.services.video_identity_vision._MAX_VIDEO_BYTES", 10
        ):
            with self.assertRaises(VideoIdentityEvaluationError) as ctx:
                evaluate_shot_video_identity(
                    shot=_LOCKED_SHOT, candidate_video_url="https://example.com/v.mp4", adapter=Mock(),
                )
        self.assertEqual(ctx.exception.reason, VideoIdentityEvaluationError.TOO_LARGE)

    def test_delegates_to_evaluate_shot_identity_with_extracted_frame(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"fake-video-bytes")

        adapter = Mock()
        adapter.compare_identity.return_value = {
            "identity_similarity": 0.9, "flags": [], "evidence": {},
            "provider": "openai", "model": "gpt-vision",
        }

        with self._patch_client(handler), patch(
            "app.services.video_identity_vision.extract_frame_data_uri",
            return_value="data:image/png;base64,AAA=",
        ) as mock_extract:
            result = evaluate_shot_video_identity(
                shot=_LOCKED_SHOT, candidate_video_url="https://example.com/v.mp4", adapter=adapter,
            )

        mock_extract.assert_called_once_with(b"fake-video-bytes")
        adapter.compare_identity.assert_called_once_with(
            reference_url="https://example.com/ref.png",
            candidate_url="data:image/png;base64,AAA=",
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["identity_similarity"], 0.9)


if __name__ == "__main__":
    unittest.main()
