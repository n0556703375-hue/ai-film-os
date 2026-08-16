"""Coverage for the S3-compatible object storage client (app.services.
object_storage) and its wiring into the two write sites that used to only
write to local disk: image upload (media_upload.py) and video persistence
(video_persistence.py).
"""

import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import settings
from app.services import object_storage

_REAL_HTTPX_CLIENT = httpx.Client

_CONFIG = {
    "object_storage_endpoint": "https://abc123.r2.cloudflarestorage.com",
    "object_storage_bucket": "film-os-media",
    "object_storage_access_key": "test-access-key",
    "object_storage_secret_key": "test-secret-key",
    "object_storage_region": "auto",
    "object_storage_public_url_base": "https://media.example.com",
}


def _mock_transport(handler):
    return httpx.MockTransport(handler)


class ObjectStorageConfigTests(unittest.TestCase):
    def setUp(self):
        self._originals = {name: getattr(settings, name) for name in _CONFIG}

    def tearDown(self):
        for name, value in self._originals.items():
            setattr(settings, name, value)

    def test_is_configured_true_when_all_fields_set(self):
        for name, value in _CONFIG.items():
            setattr(settings, name, value)
        self.assertTrue(object_storage.is_configured())

    def test_is_configured_false_when_any_required_field_missing(self):
        # object_storage_region is the one optional field — it defaults to
        # "auto" (Cloudflare R2's own default) when left unset.
        required_fields = [name for name in _CONFIG if name != "object_storage_region"]
        for name, value in _CONFIG.items():
            setattr(settings, name, value)
        for missing in required_fields:
            with self.subTest(missing=missing):
                setattr(settings, missing, "")
                self.assertFalse(object_storage.is_configured())
                setattr(settings, missing, _CONFIG[missing])

    def test_upload_raises_when_not_configured(self):
        for name in _CONFIG:
            setattr(settings, name, "")
        with self.assertRaises(object_storage.ObjectStorageError) as ctx:
            object_storage.upload(b"data", "uploads/shot-1/x.png", "image/png")
        self.assertEqual(ctx.exception.reason, object_storage.ObjectStorageError.NOT_CONFIGURED)


class ObjectStorageRequestTests(unittest.TestCase):
    def setUp(self):
        self._originals = {name: getattr(settings, name) for name in _CONFIG}
        for name, value in _CONFIG.items():
            setattr(settings, name, value)

    def tearDown(self):
        for name, value in self._originals.items():
            setattr(settings, name, value)

    def _patch_client(self, handler):
        return unittest.mock.patch(
            "app.services.object_storage.httpx.Client",
            lambda **kwargs: _REAL_HTTPX_CLIENT(transport=_mock_transport(handler), **kwargs),
        )

    def test_upload_success_returns_public_url(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization", "")
            seen["content_type"] = request.headers.get("content-type", "")
            return httpx.Response(200)

        with self._patch_client(handler):
            url = object_storage.upload(b"hello world", "uploads/shot-1/abc.png", "image/png")

        self.assertEqual(url, "https://media.example.com/uploads/shot-1/abc.png")
        self.assertEqual(seen["method"], "PUT")
        self.assertIn("/film-os-media/uploads/shot-1/abc.png", seen["url"])
        self.assertTrue(seen["auth"].startswith("AWS4-HMAC-SHA256 Credential=test-access-key/"))
        self.assertEqual(seen["content_type"], "image/png")

    def test_upload_failure_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, content=b"Forbidden")

        with self._patch_client(handler):
            with self.assertRaises(object_storage.ObjectStorageError) as ctx:
                object_storage.upload(b"data", "uploads/shot-1/x.png", "image/png")
        self.assertEqual(ctx.exception.reason, object_storage.ObjectStorageError.UPLOAD_FAILED)

    def test_two_uploads_with_distinct_keys_do_not_collide(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        with self._patch_client(handler):
            url_a = object_storage.upload(b"a", "uploads/shot-1/a.png", "image/png")
            url_b = object_storage.upload(b"b", "uploads/shot-1/b.png", "image/png")

        self.assertNotEqual(url_a, url_b)

    def test_delete_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "DELETE")
            return httpx.Response(204)

        with self._patch_client(handler):
            object_storage.delete("uploads/shot-1/abc.png")  # must not raise

    def test_delete_of_already_missing_key_is_not_an_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        with self._patch_client(handler):
            object_storage.delete("uploads/shot-1/missing.png")  # must not raise

    def test_delete_failure_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        with self._patch_client(handler):
            with self.assertRaises(object_storage.ObjectStorageError) as ctx:
                object_storage.delete("uploads/shot-1/x.png")
        self.assertEqual(ctx.exception.reason, object_storage.ObjectStorageError.DELETE_FAILED)

    def test_exists_true_for_200(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "HEAD")
            return httpx.Response(200)

        with self._patch_client(handler):
            self.assertTrue(object_storage.exists("uploads/shot-1/abc.png"))

    def test_exists_false_for_404(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        with self._patch_client(handler):
            self.assertFalse(object_storage.exists("uploads/shot-1/missing.png"))

    def test_unreachable_endpoint_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        with self._patch_client(handler):
            with self.assertRaises(object_storage.ObjectStorageError) as ctx:
                object_storage.exists("uploads/shot-1/abc.png")
        self.assertEqual(ctx.exception.reason, object_storage.ObjectStorageError.UNREACHABLE)


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class MediaUploadObjectStorageWiringTests(unittest.TestCase):
    """When object storage is configured, the upload flow must use it
    instead of local disk, and return its public URL unchanged."""

    def setUp(self):
        self._originals = {name: getattr(settings, name) for name in _CONFIG}
        for name, value in _CONFIG.items():
            setattr(settings, name, value)
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_media_path = settings.generated_media_path
        settings.generated_media_path = Path(self.tempdir.name)

    def tearDown(self):
        for name, value in self._originals.items():
            setattr(settings, name, value)
        settings.generated_media_path = self.original_media_path
        self.tempdir.cleanup()

    def test_upload_goes_to_object_storage_when_configured(self):
        from app.services.media_upload import validate_and_store_upload

        with unittest.mock.patch(
            "app.services.media_upload.object_storage.upload",
            return_value="https://media.example.com/uploads/shot-9/fake.png",
        ) as mock_upload:
            result = validate_and_store_upload(9, "image/png", _png_bytes())

        mock_upload.assert_called_once()
        called_key = mock_upload.call_args.args[1]
        self.assertTrue(called_key.startswith("uploads/shot-9/"))
        self.assertEqual(result["url"], "https://media.example.com/uploads/shot-9/fake.png")
        # Nothing should have been written to local disk in this mode.
        self.assertEqual(list(settings.generated_media_path.rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
