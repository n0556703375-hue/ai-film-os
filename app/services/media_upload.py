"""Image upload validation and persistence for shot media.

Never trusts the client-supplied filename as a filesystem path component —
only the content-sniffed MIME type (cross-checked by actually decoding the
image with Pillow) determines the stored extension. The stored filename is
always a fresh UUID, so nothing derived from user input ever reaches the
filesystem path (or object storage key).

Storage backend: app.services.object_storage when configured (survives a
deploy/restart), local disk under GENERATED_MEDIA_PATH otherwise — see that
module's docstring for the required environment variables. The local-disk
path is unconditionally kept as a fallback so the app keeps working
out of the box in development and on any host with a persistent disk.
"""

import io
import logging
import uuid

from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.services import object_storage

logger = logging.getLogger(__name__)

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
    relative_key = f"uploads/shot-{int(shot_id)}/{filename}"

    if object_storage.is_configured():
        url = object_storage.upload(content, relative_key, normalized_type)
    else:
        logger.warning(
            "object_storage is not configured — storing upload on local disk, "
            "which will NOT survive a deploy/restart without a persistent disk."
        )
        directory = settings.generated_media_path / "uploads" / f"shot-{int(shot_id)}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_bytes(content)
        url = f"/generated/{relative_key}"

    return {
        "url": url,
        "size_bytes": len(content),
        "content_type": normalized_type,
    }
