"""In-process accumulation for chunked screenplay text uploads.

Purely a transport-layer workaround: some networks (observed in production
— an Israeli ISP/organizational content-filtering proxy, "Rimon", returning
an HTML block page with HTTP 200) reject a POST body above some size
threshold, but pass small POSTs to the same endpoint through untouched.
Splitting the raw screenplay text into small chunks and reassembling them
here sidesteps that without changing anything about how the screenplay is
understood: a chunk is never parsed, validated, or interpreted on its own
— app.services.screenplay_import_service only ever sees the complete,
reassembled source text, in one call, exactly as the single-shot endpoint
already behaves. The two-stage import flow's guarantees are unchanged.

In-memory (not persisted) because the app runs as a single worker process
(WEB_CONCURRENCY=1 in render.yaml), matching the existing background
worker's same-process assumption elsewhere in this codebase. An upload
that's started but never finished (chunks sent, then abandoned) is swept
by a TTL instead of leaking memory forever.
"""

import time
from dataclasses import dataclass, field

MAX_CHUNK_CHARS = 8000
MAX_TOTAL_CHUNKS = 3000  # guards against a lied-about total_chunks -> ~24MB cap
UPLOAD_TTL_SECONDS = 30 * 60


class ChunkedUploadError(ValueError):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


@dataclass
class _PendingUpload:
    total_chunks: int
    project_id: int
    import_run_id: int | None
    chunks: dict[int, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)


_pending: dict[str, _PendingUpload] = {}


def _sweep_expired() -> None:
    now = time.monotonic()
    expired = [key for key, upload in _pending.items() if now - upload.created_at > UPLOAD_TTL_SECONDS]
    for key in expired:
        _pending.pop(key, None)


def receive_chunk(
    *,
    upload_id: str,
    chunk_index: int,
    total_chunks: int,
    chunk_text: str,
    project_id: int,
    import_run_id: int | None,
) -> dict:
    """Record one chunk. Returns either a progress dict or the fully
    reassembled text once every chunk for this upload_id has arrived.
    """
    _sweep_expired()

    if total_chunks < 1 or total_chunks > MAX_TOTAL_CHUNKS:
        raise ChunkedUploadError("invalid_chunk_count")
    if chunk_index < 0 or chunk_index >= total_chunks:
        raise ChunkedUploadError("invalid_chunk_index")
    if len(chunk_text) > MAX_CHUNK_CHARS:
        raise ChunkedUploadError("chunk_too_large")

    pending = _pending.get(upload_id)
    if pending is None:
        pending = _PendingUpload(
            total_chunks=total_chunks, project_id=project_id, import_run_id=import_run_id,
        )
        _pending[upload_id] = pending

    if (
        pending.total_chunks != total_chunks
        or pending.project_id != project_id
        or pending.import_run_id != import_run_id
    ):
        raise ChunkedUploadError("upload_mismatch")

    pending.chunks[chunk_index] = chunk_text

    if len(pending.chunks) < pending.total_chunks:
        return {
            "completed": False,
            "upload_id": upload_id,
            "received_chunks": len(pending.chunks),
            "total_chunks": pending.total_chunks,
        }

    full_text = "".join(pending.chunks[i] for i in range(pending.total_chunks))
    _pending.pop(upload_id, None)
    return {"completed": True, "screenplay_text": full_text}
