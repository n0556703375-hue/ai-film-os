import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import httpx

from app.core.config import settings
from app.services import object_storage
from app.services.video_persistence import (
    MAX_VIDEO_BYTES,
    VideoPersistenceError,
    persist_remote_video,
)

_REAL_HTTPX_CLIENT = httpx.Client

# A minimal valid MP4 "ftyp" box header followed by arbitrary payload bytes —
# enough for the magic-byte sniff without needing a real encoded video.
_FAKE_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100


def _mock_transport(responses):
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        status, headers, body = responses[state["i"]]
        state["i"] += 1
        return httpx.Response(status, headers=headers, content=body, request=request)

    return httpx.MockTransport(handler)


class VideoPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_media_path = settings.generated_media_path
        settings.generated_media_path = Path(self.tempdir.name)

    def tearDown(self):
        settings.generated_media_path = self.original_media_path
        self.tempdir.cleanup()

    def _patch_client(self, transport):
        return unittest.mock.patch(
            "app.services.video_persistence.httpx.Client",
            lambda **kwargs: _REAL_HTTPX_CLIENT(transport=transport, **kwargs),
        )

    # 1. successful remote video persistence -------------------------------
    def test_successful_persistence_writes_file_and_returns_metadata(self):
        transport = _mock_transport([
            (200, {"content-type": "video/mp4"}, _FAKE_MP4_BYTES),
        ])
        with self._patch_client(transport):
            result = persist_remote_video("https://fal.media/files/abc/video.mp4", shot_id=5)

        self.assertTrue(result["url"].startswith("/generated/videos/shot-5/"))
        self.assertTrue(result["url"].endswith(".mp4"))
        self.assertEqual(result["size_bytes"], len(_FAKE_MP4_BYTES))
        stored_path = settings.generated_media_path / result["url"].removeprefix("/generated/")
        self.assertTrue(stored_path.exists())
        self.assertEqual(stored_path.read_bytes(), _FAKE_MP4_BYTES)
        # No leftover temp files.
        leftovers = [p for p in stored_path.parent.iterdir() if p.name.startswith(".download-")]
        self.assertEqual(leftovers, [])

    # 2. private URL rejected -----------------------------------------------
    def test_private_host_rejected(self):
        with self.assertRaises(VideoPersistenceError) as ctx:
            persist_remote_video("https://127.0.0.1/video.mp4", shot_id=1)
        self.assertEqual(ctx.exception.reason, VideoPersistenceError.PRIVATE_HOST)

    def test_localhost_rejected(self):
        with self.assertRaises(VideoPersistenceError) as ctx:
            persist_remote_video("https://localhost/video.mp4", shot_id=1)
        self.assertEqual(ctx.exception.reason, VideoPersistenceError.PRIVATE_HOST)

    # 3. HTTP URL rejected ----------------------------------------------------
    def test_non_https_url_rejected(self):
        for url in ("http://fal.media/video.mp4", "ftp://fal.media/video.mp4"):
            with self.subTest(url=url):
                with self.assertRaises(VideoPersistenceError) as ctx:
                    persist_remote_video(url, shot_id=1)
                self.assertEqual(ctx.exception.reason, VideoPersistenceError.NOT_HTTPS)

    # 4. redirect to private host rejected ------------------------------------
    def test_redirect_to_private_host_rejected(self):
        transport = _mock_transport([
            (302, {"location": "https://169.254.169.254/video.mp4"}, b""),
        ])
        with self._patch_client(transport):
            with self.assertRaises(VideoPersistenceError) as ctx:
                persist_remote_video("https://fal.media/redirect.mp4", shot_id=1)
        self.assertEqual(ctx.exception.reason, VideoPersistenceError.PRIVATE_HOST)

    def test_redirect_to_public_host_is_followed(self):
        transport = _mock_transport([
            (302, {"location": "https://cdn2.fal.media/final.mp4"}, b""),
            (200, {"content-type": "video/mp4"}, _FAKE_MP4_BYTES),
        ])
        with self._patch_client(transport):
            result = persist_remote_video("https://fal.media/redirect.mp4", shot_id=1)
        self.assertTrue(result["url"].endswith(".mp4"))

    def test_too_many_redirects_rejected(self):
        responses = [(302, {"location": f"https://fal.media/hop{i}"}, b"") for i in range(10)]
        transport = _mock_transport(responses)
        with self._patch_client(transport):
            with self.assertRaises(VideoPersistenceError) as ctx:
                persist_remote_video("https://fal.media/start", shot_id=1)
        self.assertEqual(ctx.exception.reason, VideoPersistenceError.TOO_MANY_REDIRECTS)

    # 5. timeout ---------------------------------------------------------------
    def test_timeout_is_reported_as_unreachable(self):
        def handler(request):
            raise httpx.TimeoutException("timed out", request=request)

        transport = httpx.MockTransport(handler)
        with self._patch_client(transport):
            with self.assertRaises(VideoPersistenceError) as ctx:
                persist_remote_video("https://fal.media/video.mp4", shot_id=1)
        self.assertEqual(ctx.exception.reason, VideoPersistenceError.UNREACHABLE)

    # 6. oversized response rejected --------------------------------------------
    def test_oversized_download_is_rejected_and_partial_file_removed(self):
        small_limit = 1024
        oversized = b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * (small_limit * 2))
        transport = _mock_transport([
            (200, {"content-type": "video/mp4"}, oversized),
        ])
        with self._patch_client(transport):
            with self.assertRaises(VideoPersistenceError) as ctx:
                persist_remote_video("https://fal.media/huge.mp4", shot_id=9, max_bytes=small_limit)
        self.assertEqual(ctx.exception.reason, VideoPersistenceError.TOO_LARGE)
        # 8. partial download cleanup -----------------------------------------
        shot_dir = settings.generated_media_path / "videos" / "shot-9"
        leftovers = list(shot_dir.iterdir()) if shot_dir.exists() else []
        self.assertEqual(leftovers, [], "a failed download must not leave any file behind")

    # 7. invalid content type rejected -------------------------------------------
    def test_html_error_page_content_type_rejected(self):
        transport = _mock_transport([
            (200, {"content-type": "text/html"}, b"<html>error</html>"),
        ])
        with self._patch_client(transport):
            with self.assertRaises(VideoPersistenceError) as ctx:
                persist_remote_video("https://fal.media/oops.mp4", shot_id=1)
        self.assertEqual(ctx.exception.reason, VideoPersistenceError.WRONG_CONTENT_TYPE)

    def test_octet_stream_with_real_mp4_bytes_is_accepted(self):
        transport = _mock_transport([
            (200, {"content-type": "application/octet-stream"}, _FAKE_MP4_BYTES),
        ])
        with self._patch_client(transport):
            result = persist_remote_video("https://fal.media/video.mp4", shot_id=1)
        self.assertTrue(result["url"].endswith(".mp4"))

    def test_octet_stream_with_non_video_bytes_is_rejected(self):
        transport = _mock_transport([
            (200, {"content-type": "application/octet-stream"}, b"not actually a video" * 5),
        ])
        with self._patch_client(transport):
            with self.assertRaises(VideoPersistenceError) as ctx:
                persist_remote_video("https://fal.media/fake.mp4", shot_id=1)
        self.assertEqual(ctx.exception.reason, VideoPersistenceError.NOT_A_VALID_VIDEO)

    # 8. partial download cleanup (network failure mid-stream) -------------------
    def test_connection_error_leaves_no_partial_file(self):
        def handler(request):
            raise httpx.ConnectError("boom", request=request)

        transport = httpx.MockTransport(handler)
        with self._patch_client(transport):
            with self.assertRaises(VideoPersistenceError):
                persist_remote_video("https://fal.media/video.mp4", shot_id=3)
        shot_dir = settings.generated_media_path / "videos" / "shot-3"
        leftovers = list(shot_dir.iterdir()) if shot_dir.exists() else []
        self.assertEqual(leftovers, [])

    # 9. UUID filename -------------------------------------------------------------
    def test_filename_is_a_fresh_uuid_each_time(self):
        transport = _mock_transport([
            (200, {"content-type": "video/mp4"}, _FAKE_MP4_BYTES),
            (200, {"content-type": "video/mp4"}, _FAKE_MP4_BYTES),
        ])
        with self._patch_client(transport):
            first = persist_remote_video("https://fal.media/video.mp4", shot_id=1)
            second = persist_remote_video("https://fal.media/video.mp4", shot_id=1)
        self.assertNotEqual(first["url"], second["url"])
        filename = first["url"].rsplit("/", 1)[-1]
        self.assertRegex(filename, r"^[0-9a-f]{32}\.mp4$")

    # 10. correct /generated/videos/... public URL --------------------------------
    def test_public_url_matches_expected_pattern(self):
        transport = _mock_transport([
            (200, {"content-type": "video/mp4"}, _FAKE_MP4_BYTES),
        ])
        with self._patch_client(transport):
            result = persist_remote_video("https://fal.media/video.mp4", shot_id=42)
        self.assertRegex(result["url"], r"^/generated/videos/shot-42/[0-9a-f]{32}\.mp4$")

    def test_never_returns_provider_url_as_persisted_url(self):
        provider_url = "https://fal.media/files/secret-signed-token/video.mp4"
        transport = _mock_transport([
            (200, {"content-type": "video/mp4"}, _FAKE_MP4_BYTES),
        ])
        with self._patch_client(transport):
            result = persist_remote_video(provider_url, shot_id=1)
        self.assertNotIn("fal.media", result["url"])
        self.assertNotIn("secret-signed-token", result["url"])


class VideoPersistenceObjectStorageWiringTests(unittest.TestCase):
    """When object storage is configured, a persisted video must go there
    instead of local disk, and never leave a local copy behind."""

    _OBJECT_STORAGE_CONFIG = {
        "object_storage_endpoint": "https://abc123.r2.cloudflarestorage.com",
        "object_storage_bucket": "film-os-media",
        "object_storage_access_key": "test-access-key",
        "object_storage_secret_key": "test-secret-key",
        "object_storage_region": "auto",
        "object_storage_public_url_base": "https://media.example.com",
    }

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_media_path = settings.generated_media_path
        settings.generated_media_path = Path(self.tempdir.name)
        self._originals = {
            name: getattr(settings, name) for name in self._OBJECT_STORAGE_CONFIG
        }
        for name, value in self._OBJECT_STORAGE_CONFIG.items():
            setattr(settings, name, value)

    def tearDown(self):
        settings.generated_media_path = self.original_media_path
        self.tempdir.cleanup()
        for name, value in self._originals.items():
            setattr(settings, name, value)

    def _patch_client(self, transport):
        return unittest.mock.patch(
            "app.services.video_persistence.httpx.Client",
            lambda **kwargs: _REAL_HTTPX_CLIENT(transport=transport, **kwargs),
        )

    def test_persisted_video_goes_to_object_storage_and_leaves_no_local_copy(self):
        transport = _mock_transport([
            (200, {"content-type": "video/mp4"}, _FAKE_MP4_BYTES),
        ])
        with self._patch_client(transport), unittest.mock.patch(
            "app.services.video_persistence.object_storage.upload",
            return_value="https://media.example.com/videos/shot-5/fake.mp4",
        ) as mock_upload:
            result = persist_remote_video("https://fal.media/files/abc/video.mp4", shot_id=5)

        mock_upload.assert_called_once()
        called_key = mock_upload.call_args.args[1]
        self.assertTrue(called_key.startswith("videos/shot-5/"))
        self.assertEqual(result["url"], "https://media.example.com/videos/shot-5/fake.mp4")
        # No local file left behind — including no leftover temp file.
        self.assertEqual(list(settings.generated_media_path.rglob("*.mp4")), [])
        self.assertEqual(
            [p for p in settings.generated_media_path.rglob("*") if p.name.startswith(".download-")],
            [],
        )

    def test_object_storage_upload_failure_is_retryable_and_leaves_no_local_copy(self):
        transport = _mock_transport([
            (200, {"content-type": "video/mp4"}, _FAKE_MP4_BYTES),
        ])
        with self._patch_client(transport), unittest.mock.patch(
            "app.services.video_persistence.object_storage.upload",
            side_effect=object_storage.ObjectStorageError(object_storage.ObjectStorageError.UPLOAD_FAILED),
        ):
            with self.assertRaises(VideoPersistenceError) as ctx:
                persist_remote_video("https://fal.media/files/abc/video.mp4", shot_id=5)

        self.assertEqual(ctx.exception.reason, VideoPersistenceError.OBJECT_STORAGE_UPLOAD_FAILED)
        self.assertTrue(ctx.exception.retryable)
        leftover_files = [p for p in settings.generated_media_path.rglob("*") if p.is_file()]
        self.assertEqual(leftover_files, [])


if __name__ == "__main__":
    unittest.main()
