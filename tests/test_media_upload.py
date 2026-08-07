"""Coverage for the image upload flow: service-level validation/storage and
the /api/shots/{shot_id}/media/upload route built on top of it."""

import asyncio
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from starlette.datastructures import Headers, UploadFile

from app.api.shots import upload_media
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots
from app.services.media_upload import (
    MAX_UPLOAD_BYTES,
    MediaUploadError,
    validate_and_store_upload,
)


def _png_bytes(size=(4, 4), color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 255, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def _webp_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 255)).save(buf, format="WEBP")
    return buf.getvalue()


class MediaUploadServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = settings.generated_media_path
        settings.generated_media_path = Path(self.tempdir.name)

    def tearDown(self):
        settings.generated_media_path = self.original_path
        self.tempdir.cleanup()

    def test_valid_png_upload_is_stored_under_uuid_filename(self):
        content = _png_bytes()
        result = validate_and_store_upload(7, "image/png", content)

        self.assertTrue(result["url"].startswith("/generated/uploads/shot-7/"))
        self.assertTrue(result["url"].endswith(".png"))
        self.assertEqual(result["size_bytes"], len(content))
        self.assertEqual(result["content_type"], "image/png")

        stored_path = settings.generated_media_path / result["url"].removeprefix("/generated/")
        self.assertTrue(stored_path.exists())
        self.assertEqual(stored_path.read_bytes(), content)

    def test_valid_jpeg_and_webp_are_accepted(self):
        jpeg_result = validate_and_store_upload(1, "image/jpeg", _jpeg_bytes())
        self.assertTrue(jpeg_result["url"].endswith(".jpg"))

        webp_result = validate_and_store_upload(1, "image/webp", _webp_bytes())
        self.assertTrue(webp_result["url"].endswith(".webp"))

    def test_content_type_with_charset_suffix_is_normalized(self):
        result = validate_and_store_upload(1, "image/png; charset=binary", _png_bytes())
        self.assertEqual(result["content_type"], "image/png")

    def test_empty_file_is_rejected(self):
        with self.assertRaises(MediaUploadError) as ctx:
            validate_and_store_upload(1, "image/png", b"")
        self.assertEqual(ctx.exception.reason, MediaUploadError.EMPTY_FILE)

    def test_unsupported_mime_type_is_rejected(self):
        for content_type in ("image/gif", "application/pdf", "text/plain", ""):
            with self.subTest(content_type=content_type):
                with self.assertRaises(MediaUploadError) as ctx:
                    validate_and_store_upload(1, content_type, _png_bytes())
                self.assertEqual(ctx.exception.reason, MediaUploadError.UNSUPPORTED_TYPE)

    def test_oversized_file_is_rejected(self):
        oversized = b"\x00" * (MAX_UPLOAD_BYTES + 1)
        with self.assertRaises(MediaUploadError) as ctx:
            validate_and_store_upload(1, "image/png", oversized)
        self.assertEqual(ctx.exception.reason, MediaUploadError.TOO_LARGE)

    def test_malformed_image_bytes_with_valid_mime_are_rejected(self):
        # A MIME type can be spoofed by the client; the bytes must actually
        # decode as an image or the upload is refused.
        not_really_an_image = b"this is definitely not PNG data" * 10
        with self.assertRaises(MediaUploadError) as ctx:
            validate_and_store_upload(1, "image/png", not_really_an_image)
        self.assertEqual(ctx.exception.reason, MediaUploadError.UNDECODABLE_IMAGE)

    def test_rejected_upload_writes_nothing_to_disk(self):
        before = list(settings.generated_media_path.rglob("*"))
        with self.assertRaises(MediaUploadError):
            validate_and_store_upload(1, "image/png", b"garbage")
        after = list(settings.generated_media_path.rglob("*"))
        self.assertEqual(before, after)

    def test_stored_filename_never_derives_from_client_input(self):
        # There is no filename parameter at all on the storage boundary —
        # only shot_id (an int) and content-derived bytes ever reach the
        # filesystem path, so path traversal via a crafted filename is
        # structurally impossible here.
        result_a = validate_and_store_upload(1, "image/png", _png_bytes())
        result_b = validate_and_store_upload(1, "image/png", _png_bytes())
        self.assertNotEqual(result_a["url"], result_b["url"])

    def test_upload_is_scoped_per_shot_directory(self):
        result_shot_1 = validate_and_store_upload(1, "image/png", _png_bytes())
        result_shot_2 = validate_and_store_upload(2, "image/png", _png_bytes())
        self.assertIn("/shot-1/", result_shot_1["url"])
        self.assertIn("/shot-2/", result_shot_2["url"])


class UploadMediaRouteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        self.original_media_path = settings.generated_media_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        settings.generated_media_path = Path(self.tempdir.name) / "generated"
        init_db()
        project = projects.create_project(
            {"name": "UploadFlow", "description": "", "visual_style": "", "rules": ""}
        )
        scene = scenes.create_scene(
            {
                "project_id": project["id"],
                "scene_number": 1,
                "title": "S",
                "status": "מתוכנן",
                "story_goal": "",
                "emotion": "",
                "conflict": "",
                "beginning": "",
                "ending": "",
                "notes": "",
            }
        )
        self.shot = shots.create_shot(
            {
                "project_id": project["id"],
                "scene_id": scene["id"],
                "shot_number": 1,
                "title": "Shot",
                "prompt": "",
                "duration_seconds": 5,
            }
        )

    def tearDown(self):
        settings.database_path = self.original_db
        settings.generated_media_path = self.original_media_path
        self.tempdir.cleanup()

    def _upload_file(self, content: bytes, content_type: str, filename: str = "photo.png") -> UploadFile:
        return UploadFile(
            file=io.BytesIO(content),
            filename=filename,
            headers=Headers({"content-type": content_type}),
        )

    def test_successful_upload_creates_media_result(self):
        upload = self._upload_file(_png_bytes(), "image/png")

        result = asyncio.run(upload_media(self.shot["id"], upload))

        self.assertEqual(result["media_type"], "image")
        self.assertEqual(result["provider"], "upload")
        self.assertEqual(result["status"], "טיוטה")
        self.assertTrue(result["url"].startswith(f"/generated/uploads/shot-{self.shot['id']}/"))
        media = shots.list_media_results(self.shot["id"])
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["url"], result["url"])

    def test_original_filename_is_stored_only_as_metadata(self):
        upload = self._upload_file(_png_bytes(), "image/png", filename="../../etc/passwd.png")

        result = asyncio.run(upload_media(self.shot["id"], upload))

        # The traversal-looking filename never influenced the storage path.
        self.assertTrue(result["url"].startswith(f"/generated/uploads/shot-{self.shot['id']}/"))
        self.assertNotIn("..", result["url"])
        self.assertEqual(result["metadata"]["original_filename"], "../../etc/passwd.png")

    def test_upload_to_missing_shot_returns_none_signal(self):
        from fastapi import HTTPException

        upload = self._upload_file(_png_bytes(), "image/png")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(upload_media(999999, upload))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_invalid_upload_returns_400_with_stable_reason(self):
        from fastapi import HTTPException

        upload = self._upload_file(b"not an image", "image/png")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(upload_media(self.shot["id"], upload))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, MediaUploadError.UNDECODABLE_IMAGE)


if __name__ == "__main__":
    unittest.main()
