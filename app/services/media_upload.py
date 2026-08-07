"""Image upload validation and safe on-disk persistence for shot media.

Never trusts the client-supplied filename as a filesystem path component —
only the content-sniffed MIME type (cross-checked by actually decoding the
image with Pillow) determines the stored extension. The stored filename is
always a fresh UUID, so nothing derived from user input ever reaches the
filesystem path.
"""

import io
import uuid

from PIL import Image, UnidentifiedImageError

from app.core.config import settings

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB — generous for a single shot reference image

_ALLOWED_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


class MediaUploadError(ValueError):
    """A stable, sanitized reason an uploaded file was rejected."""

    EMPTY_FILE = "empty_file"
    UNSUPPORTED_TYPE = "unsupported_type"
    TOO_LARGE = "too_large"
    UNDECODABLE_IMAGE = "undecodable_image"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Image upload rejected: {reason}")


def validate_and_store_upload(shot_id: int, content_type: str, content: bytes) -> dict:
    """Validate an uploaded image and persist it under a safe, unique path.

    Returns:
        {"url": "/generated/uploads/shot-{id}/<uuid>.<ext>", "size_bytes": int,
         "content_type": str}

    Raises ``MediaUploadError`` with a stable reason on any validation
    failure. Nothing is written to disk unless every check — non-empty,
    allowed MIME type, size limit, and actual image decodability — passes.
    """
    if not content:
        raise MediaUploadError(MediaUploadError.EMPTY_FILE)
    if len(content) > MAX_UPLOAD_BYTES:
        raise MediaUploadError(MediaUploadError.TOO_LARGE)

    normalized_type = (content_type or "").split(";")[0].strip().lower()
    extension = _ALLOWED_CONTENT_TYPES.get(normalized_type)
    if not extension:
        raise MediaUploadError(MediaUploadError.UNSUPPORTED_TYPE)

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise MediaUploadError(MediaUploadError.UNDECODABLE_IMAGE)

    filename = f"{uuid.uuid4().hex}.{extension}"
    directory = settings.generated_media_path / "uploads" / f"shot-{int(shot_id)}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(content)

    return {
        "url": f"/generated/uploads/shot-{int(shot_id)}/{filename}",
        "size_bytes": len(content),
        "content_type": normalized_type,
    }
