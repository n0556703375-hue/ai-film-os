"""In-process accumulation for chunked screenplay text uploads.

Purely a transport-layer workaround: some networks (observed in production
— an Israeli ISP/organizational content-filtering proxy, "Rimon", returning
an HTML block page with HTTP 200 and a `Rimon: RWC_BLOCK` header) reject a
POST body above some size threshold, but pass small POSTs to the same
endpoint through untouched. The exact threshold isn't knowable up front —
production traffic showed both a ~7.4KB request and a ~61KB request
blocked, with only very small requests confirmed to pass — so the client
(screenplay-import-ui.js) sends adaptively-sized pieces and shrinks on
failure rather than assuming a fixed chunk size will always work.

Chunks are appended here in arrival order (the client always awaits one
chunk's response before sending the next, so no reordering is needed) and
reassembled once the caller marks a chunk `is_final`. A chunk is never
parsed, validated, or interpreted on its own —
app.services.screenplay_import_service only ever sees the complete,
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

MAX_CHUNK_CHARS = 20000  # generous abuse guard; the client's real working
                          # size is far smaller and adapts to the network
MAX_PARTS_PER_UPLOAD = 5000  # guards total memory for one upload
UPLOAD_TTL_SECONDS = 30 * 60


class ChunkedUploadError(ValueError):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


@dataclass
class _PendingUpload:
    project_id: int
    import_run_id: int | None
    parts: list[str] = field(default_factory=list)
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
    chunk_text: str,
    is_final: bool,
    project_id: int,
    import_run_id: int | None,
) -> dict:
    """Append one piece of screenplay text. Returns a small progress dict,
    or — once `is_final` is True — the fully reassembled text.
    """
    _sweep_expired()

    if len(chunk_text) > MAX_CHUNK_CHARS:
        raise ChunkedUploadError("chunk_too_large")

    pending = _pending.get(upload_id)
    if pending is None:
        pending = _PendingUpload(project_id=project_id, import_run_id=import_run_id)
        _pending[upload_id] = pending

    if pending.project_id != project_id or pending.import_run_id != import_run_id:
        raise ChunkedUploadError("upload_mismatch")
    if len(pending.parts) >= MAX_PARTS_PER_UPLOAD:
        raise ChunkedUploadError("too_many_chunks")

    pending.parts.append(chunk_text)

    if not is_final:
        return {
            "completed": False,
            "upload_id": upload_id,
            "received_chars": sum(len(part) for part in pending.parts),
        }

    full_text = "".join(pending.parts)
    _pending.pop(upload_id, None)
    return {"completed": True, "screenplay_text": full_text}
