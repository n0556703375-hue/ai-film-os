"""Sync.so lip-sync adapter for AI Film OS.

Takes a generated video URL and dialogue audio URL, submits a lip-sync job
to sync.so, and either polls in-process (apply_lip_sync) or lets the caller
poll step-by-step (submit_sync_job + check_sync_job).

Sync.so is optional: without SYNC_API_KEY the Kling video passes through unchanged.
A Sync failure never cancels a Kling video that has already been completed.

Redaction contract
------------------
Nothing this module raises, returns or logs may carry provider response
bodies, API keys, signed URLs, or the video/audio URLs being processed.
Failures are reported as a stable category from ``SyncErrorCategory`` plus,
at most, a numeric HTTP status. Callers persist these strings into
``media_jobs.last_error``, so they must stay free of caller-supplied and
provider-supplied text.

Environment variables required:
    SYNC_API_KEY  — Sync.so API key from https://sync.so
    SYNC_API_BASE — optional override (default: https://api.sync.so)
"""

import time
from typing import Callable

import httpx

from app.core.config import settings

_POLL_INTERVAL = 8
_MAX_POLLS = 90
SYNC_SUPPORTED_MODELS = frozenset(
    {"sync-3", "lipsync-2", "lipsync-2-pro", "lipsync-1.9.0-beta"}
)


class SyncErrorCategory:
    """Stable, sanitized failure categories safe for logs and persistence."""

    NOT_CONFIGURED = "not_configured"
    INVALID_CREDENTIALS = "invalid_credentials"
    NETWORK_ERROR = "network_error"
    PROVIDER_ERROR = "provider_error"
    MALFORMED_RESPONSE = "malformed_response"
    MISSING_JOB_ID = "missing_job_id"
    MISSING_OUTPUT_URL = "missing_output_url"
    JOB_FAILED = "job_failed"
    INVALID_MODEL = "invalid_model"
    UNKNOWN_STATUS = "unknown_status"
    TIMEOUT = "timeout"
    UNEXPECTED_ERROR = "unexpected_error"


class SyncProviderNotConfigured(RuntimeError):
    """Credentials are absent or rejected. Message never contains the key."""

    def __init__(self, message: str, *, category: str = SyncErrorCategory.NOT_CONFIGURED):
        self.category = category
        super().__init__(message)


class SyncProviderError(RuntimeError):
    """A sanitized Sync.so failure.

    ``str(exc)`` is deliberately built only from a fixed prefix, the stable
    category and an optional numeric HTTP status, so it stays safe when the
    worker writes it into ``media_jobs.last_error``.
    """

    def __init__(self, category: str, *, status_code: int | None = None):
        self.category = category
        self.status_code = status_code
        suffix = f" (HTTP {int(status_code)})" if isinstance(status_code, int) else ""
        super().__init__(f"Sync.so lip-sync failed: {category}{suffix}")


def _headers() -> dict:
    return {
        "x-api-key": settings.sync_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "AI-Film-OS/1.0",
    }


def _require_key() -> None:
    if not settings.sync_api_key:
        raise SyncProviderNotConfigured(
            "SYNC_API_KEY אינו מוגדר. הגדר את המפתח בסביבת ההפעלה."
        )


def _resolve_model(model: str | None) -> str:
    selected = model if model is not None else settings.sync_default_model
    if selected not in SYNC_SUPPORTED_MODELS:
        raise SyncProviderError(SyncErrorCategory.INVALID_MODEL)
    return selected


def _json_or_error(resp: httpx.Response) -> dict:
    """Parse a JSON object, never echoing the body on failure."""
    try:
        body = resp.json()
    except Exception as exc:
        raise SyncProviderError(
            SyncErrorCategory.MALFORMED_RESPONSE, status_code=resp.status_code
        ) from exc
    if not isinstance(body, dict):
        raise SyncProviderError(
            SyncErrorCategory.MALFORMED_RESPONSE, status_code=resp.status_code
        )
    return body


def _guard_status(resp: httpx.Response, expected_statuses: set[int]) -> None:
    """Translate HTTP status into sanitized exceptions."""
    if resp.status_code in {401, 403}:
        raise SyncProviderNotConfigured(
            "Sync.so דחה את מפתח ה-API. יש לעדכן את SYNC_API_KEY.",
            category=SyncErrorCategory.INVALID_CREDENTIALS,
        )
    if resp.status_code not in expected_statuses:
        raise SyncProviderError(
            SyncErrorCategory.PROVIDER_ERROR, status_code=resp.status_code
        )


def submit_sync_job(video_url: str, audio_url: str, model: str | None = None) -> str:
    """POST to Sync.so, return job_id immediately — no polling, no sleep.

    Args:
        video_url: URL of the Kling-generated video.
        audio_url: URL of the approved dialogue audio file (MP3 or WAV).
        model: Sync.so model identifier.

    Returns:
        Sync.so job_id.
    """
    _require_key()
    selected_model = _resolve_model(model)

    payload = {
        "model": selected_model,
        "input": [
            {"type": "video", "url": video_url},
            {"type": "audio", "url": audio_url},
        ],
    }

    url = f"{settings.sync_api_base}/v2/generate"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=_headers())
    except httpx.RequestError as exc:
        # httpx errors stringify with the full request URL — never propagate them.
        raise SyncProviderError(SyncErrorCategory.NETWORK_ERROR) from exc

    _guard_status(resp, {201})
    body = _json_or_error(resp)
    job_id = body.get("id")
    if not job_id or not isinstance(job_id, str):
        raise SyncProviderError(SyncErrorCategory.MISSING_JOB_ID)
    return job_id


def check_sync_job(job_id: str) -> dict:
    """Single GET to check Sync.so job status — no sleep.

    Returns:
        {"status": "pending"|"COMPLETED"|"FAILED",
         "output_url": str,
         "error_category": str,
         "error": str}

    ``error``/``error_category`` carry only a stable category — never the
    provider's free-text failure message.
    """
    _require_key()
    url = f"{settings.sync_api_base}/v2/generate/{job_id}"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=_headers())
    except httpx.RequestError as exc:
        raise SyncProviderError(SyncErrorCategory.NETWORK_ERROR) from exc

    _guard_status(resp, {200})
    data = _json_or_error(resp)
    status = data.get("status", "")

    if status == "COMPLETED":
        output_url = data.get("outputUrl") or ""
        if not output_url or not isinstance(output_url, str):
            raise SyncProviderError(SyncErrorCategory.MISSING_OUTPUT_URL)
        return {
            "status": "COMPLETED",
            "output_url": output_url,
            "error_category": "",
            "error": "",
        }
    if status in {"FAILED", "REJECTED"}:
        # data["error"] is provider free text and is deliberately dropped.
        return {
            "status": "FAILED",
            "output_url": "",
            "error_category": SyncErrorCategory.JOB_FAILED,
            "error": SyncErrorCategory.JOB_FAILED,
        }
    if status in {"PENDING", "PROCESSING"}:
        return {
            "status": "pending",
            "output_url": "",
            "error_category": "",
            "error": "",
        }
    raise SyncProviderError(SyncErrorCategory.UNKNOWN_STATUS)


def apply_lip_sync(
    video_url: str,
    audio_url: str,
    model: str | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Submit a lip-sync job and return the URL of the synced video.

    Called from the worker process (not from HTTP handlers).
    Sync failure should be caught by the caller — it must not cancel the Kling video.

    Returns:
        URL of the lip-synced video.
    """
    job_id = submit_sync_job(video_url, audio_url, model)
    for _ in range(_MAX_POLLS):
        sleep(_POLL_INTERVAL)
        result = check_sync_job(job_id)
        if result["status"] == "COMPLETED":
            return result["output_url"]
        if result["status"] == "FAILED":
            raise SyncProviderError(SyncErrorCategory.JOB_FAILED)
    raise TimeoutError(
        f"Sync.so לא השלים את הסנכרון אחרי {_MAX_POLLS * _POLL_INTERVAL} שניות."
    )


def check_sync_connection() -> dict:
    """Report whether Sync.so credentials can be proven valid.

    Uses the documented, authenticated and non-billable ``GET /v2/models``
    endpoint. Only a valid JSON model list containing a supported lip-sync
    model proves that the configured account can use this adapter.
    """
    if not settings.sync_api_key:
        return {
            "connected": False,
            "status": SyncErrorCategory.NOT_CONFIGURED,
            "message": "SYNC_API_KEY אינו מוגדר.",
        }
    url = f"{settings.sync_api_base}/v2/models"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=_headers())
    except httpx.RequestError:
        return {
            "connected": False,
            "status": "indeterminate",
            "message": "לא ניתן להשלים כרגע את בדיקת החיבור ל-Sync.so.",
        }

    if resp.status_code in {401, 403}:
        return {
            "connected": False,
            "status": SyncErrorCategory.INVALID_CREDENTIALS,
            "message": "Sync.so דחה את מפתח ה-API.",
        }
    if resp.status_code != 200:
        return {
            "connected": False,
            "status": "indeterminate",
            "message": "Sync.so לא השלים את בדיקת החיבור.",
        }

    try:
        models = resp.json()
    except Exception:
        models = None
    if not isinstance(models, list):
        return {
            "connected": False,
            "status": "indeterminate",
            "message": "Sync.so החזיר תגובת חיבור לא תקינה.",
        }

    available = {
        item.get("id")
        for item in models
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if not available.intersection(SYNC_SUPPORTED_MODELS):
        return {
            "connected": False,
            "status": "unsupported_models",
            "message": "החשבון מחובר אך אינו מציג מודל lip-sync נתמך.",
        }
    return {
        "connected": True,
        "status": "connected",
        "message": "Sync.so מחובר ומוכן.",
    }
