"""Download a completed provider video and store AI Film OS's own durable
copy, so the browser never depends on an external (fal.ai) video URL for
playback — some networks intercept/block third-party CDN domains, and a
provider's signed URL can also expire.

Mirrors the safety model already used for uploads (app/services/
media_upload.py) and outbound image fetches (app/services/public_media_url.py):
the source URL is HTTPS-only and rejected if it resolves to a private/
loopback/link-local/reserved host (each redirect hop is re-validated, not
just the original URL); the download is size-bounded and streamed to a temp
file; the temp file is only treated as a real, complete download after it
actually looks like an MP4.

Storage backend: the validated download is always first staged to a local
temp file (bounding memory regardless of backend). From there it either goes
to app.services.object_storage when configured — survives a deploy/restart —
or is atomically renamed into place under GENERATED_MEDIA_PATH otherwise. A
failed or partial download never leaves a file behind on either backend.
"""

import ipaddress
import logging
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings
from app.services import object_storage

logger = logging.getLogger(__name__)

MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB — generous for a 4-15s 720p clip
_DOWNLOAD_TIMEOUT_SECONDS = 60.0
_MAX_REDIRECTS = 5
_CHUNK_BYTES = 1024 * 1024

# fal.ai has been observed serving completed Seedance output as either the
# documented video/mp4 or a generic application/octet-stream; the latter is
# accepted only after the downloaded bytes are confirmed to start with an
# MP4 ftyp box (see _looks_like_mp4), never on the declared header alone.
_ALLOWED_VIDEO_CONTENT_TYPES = {"video/mp4", "application/octet-stream"}


class VideoPersistenceError(RuntimeError):
    """A stable, sanitized reason a provider video could not be persisted.

    Deliberately a ``RuntimeError``, not a ``ValueError``: app.worker.
    process_one_job() treats a bare ``ValueError`` as non-retryable, but a
    persistence failure must always be retryable — the already-paid provider
    generation succeeded and only needs to be re-downloaded, never redone.
    """

    CATEGORY = "video_persistence_failed"

    NOT_HTTPS = "not_https"
    PRIVATE_HOST = "private_host"
    UNREACHABLE = "unreachable"
    WRONG_CONTENT_TYPE = "wrong_content_type"
    NOT_A_VALID_VIDEO = "not_a_valid_video"
    TOO_LARGE = "too_large"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    WRITE_FAILED = "write_failed"
    OBJECT_STORAGE_UPLOAD_FAILED = "object_storage_upload_failed"

    def __init__(self, reason: str):
        self.reason = reason
        self.category = self.CATEGORY
        self.retryable = True
        super().__init__(f"{self.CATEGORY}: {reason}")


def _is_public_host(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def _looks_like_mp4(head: bytes) -> bool:
    # ISO base media file format (MP4): the first box is a 4-byte size
    # followed by the literal ASCII type "ftyp".
    return len(head) >= 8 and head[4:8] == b"ftyp"


def _stream_to_disk(response: httpx.Response, shot_id: int, content_type: str, max_bytes: int) -> dict:
    staging_dir = settings.generated_media_path / "videos" / f"shot-{int(shot_id)}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.mp4"
    relative_key = f"videos/shot-{int(shot_id)}/{filename}"

    fd, tmp_path_str = tempfile.mkstemp(dir=str(staging_dir), prefix=".download-", suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    written = 0
    first_chunk = b""
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            for chunk in response.iter_bytes(chunk_size=_CHUNK_BYTES):
                if not first_chunk:
                    first_chunk = chunk[:16]
                written += len(chunk)
                if written > max_bytes:
                    raise VideoPersistenceError(VideoPersistenceError.TOO_LARGE)
                tmp_file.write(chunk)
    except VideoPersistenceError:
        tmp_path.unlink(missing_ok=True)
        raise
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise VideoPersistenceError(VideoPersistenceError.WRITE_FAILED)

    if written == 0 or not _looks_like_mp4(first_chunk):
        tmp_path.unlink(missing_ok=True)
        raise VideoPersistenceError(VideoPersistenceError.NOT_A_VALID_VIDEO)

    if object_storage.is_configured():
        try:
            data = tmp_path.read_bytes()
            url = object_storage.upload(data, relative_key, content_type)
        except (OSError, object_storage.ObjectStorageError):
            raise VideoPersistenceError(VideoPersistenceError.OBJECT_STORAGE_UPLOAD_FAILED)
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        logger.warning(
            "object_storage is not configured — storing video on local disk, "
            "which will NOT survive a deploy/restart without a persistent disk."
        )
        destination = staging_dir / filename
        try:
            tmp_path.rename(destination)
        except OSError:
            tmp_path.unlink(missing_ok=True)
            raise VideoPersistenceError(VideoPersistenceError.WRITE_FAILED)
        url = f"/generated/{relative_key}"

    return {
        "url": url,
        "size_bytes": written,
        "content_type": content_type,
    }


def persist_remote_video(source_url: str, shot_id: int, *, max_bytes: int = MAX_VIDEO_BYTES) -> dict:
    """Download a completed provider video and store it under GENERATED_MEDIA_PATH.

    Never trusts a provider-supplied filename — the stored filename is
    always a fresh UUID. Returns:
        {"url": "/generated/videos/shot-{id}/<uuid>.mp4", "size_bytes": int,
         "content_type": str}

    Raises ``VideoPersistenceError`` on any failure — the caller (the video
    job worker) must not mark the job completed and must not treat this as a
    reason to resubmit to the provider.
    """
    current = source_url
    for _ in range(_MAX_REDIRECTS + 1):
        parsed = urlparse(current)
        if parsed.scheme != "https" or not parsed.hostname:
            raise VideoPersistenceError(VideoPersistenceError.NOT_HTTPS)
        if not _is_public_host(parsed.hostname):
            raise VideoPersistenceError(VideoPersistenceError.PRIVATE_HOST)

        try:
            with httpx.Client(timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=False) as client:
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise VideoPersistenceError(VideoPersistenceError.UNREACHABLE)
                        current = urljoin(current, location)
                        continue

                    if not (200 <= response.status_code < 300):
                        raise VideoPersistenceError(VideoPersistenceError.UNREACHABLE)

                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if content_type not in _ALLOWED_VIDEO_CONTENT_TYPES:
                        raise VideoPersistenceError(VideoPersistenceError.WRONG_CONTENT_TYPE)

                    return _stream_to_disk(response, shot_id, content_type, max_bytes)
        except httpx.RequestError:
            raise VideoPersistenceError(VideoPersistenceError.UNREACHABLE)
    raise VideoPersistenceError(VideoPersistenceError.TOO_MANY_REDIRECTS)
