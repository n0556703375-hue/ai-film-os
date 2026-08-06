"""Sync.so lip-sync adapter for AI Film OS.

Takes a generated video URL and dialogue audio URL, submits a lip-sync job
to sync.so, and either polls in-process (apply_lip_sync) or lets the caller
poll step-by-step (submit_sync_job + check_sync_job).

Sync.so is optional: without SYNC_API_KEY the Kling video passes through unchanged.
A Sync failure never cancels a Kling video that has already been completed.

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


class SyncProviderNotConfigured(RuntimeError):
    pass


def _headers() -> dict:
    return {
        "x-api-key": settings.sync_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "AI-Film-OS/1.0",
    }


def submit_sync_job(video_url: str, audio_url: str, model: str = "sync-2") -> str:
    """POST to Sync.so, return job_id immediately — no polling, no sleep.

    Args:
        video_url: URL of the Kling-generated video.
        audio_url: URL of the approved dialogue audio file (MP3 or WAV).
        model: Sync.so model — sync-2 (fast) or sync-3 (highest quality).

    Returns:
        Sync.so job_id.
    """
    if not settings.sync_api_key:
        raise SyncProviderNotConfigured(
            "SYNC_API_KEY אינו מוגדר. הגדר את המפתח בסביבת ההפעלה."
        )

    payload = {
        "model": model,
        "input": [
            {"type": "video", "url": video_url},
            {"type": "audio", "url": audio_url},
        ],
        "options": {
            "output_format": "mp4",
            "sync_mode": "bounce",
        },
    }

    url = f"{settings.sync_api_base}/v2/generate"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload, headers=_headers())

    if resp.status_code == 401:
        raise SyncProviderNotConfigured(
            "Sync.so דחה את מפתח ה-API. יש לעדכן את SYNC_API_KEY."
        )
    if resp.status_code not in {200, 201, 202}:
        raise RuntimeError(
            f"Sync.so החזיר שגיאה {resp.status_code}: {resp.text[:300]}"
        )

    body = resp.json()
    job_id = body.get("id") or body.get("job_id")
    if not job_id:
        raise RuntimeError(f"Sync.so לא החזיר job_id: {resp.text[:300]}")
    return job_id


def check_sync_job(job_id: str) -> dict:
    """Single GET to check Sync.so job status — no sleep.

    Returns:
        {"status": "pending"|"COMPLETED"|"FAILED", "output_url": str, "error": str}
    """
    url = f"{settings.sync_api_base}/v2/generate/{job_id}"
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(url, headers=_headers())
    if resp.status_code != 200:
        raise RuntimeError(
            f"Sync.so polling שגיאה {resp.status_code}: {resp.text[:200]}"
        )
    data = resp.json()
    status = data.get("status", "")
    if status == "COMPLETED":
        output_url = data.get("outputUrl") or data.get("output_url") or ""
        if not output_url:
            raise RuntimeError("Sync.so דיווח על הצלחה אבל לא החזיר URL.")
        return {"status": "COMPLETED", "output_url": output_url, "error": ""}
    if status in {"FAILED", "ERROR"}:
        return {"status": "FAILED", "output_url": "", "error": data.get("error", "סיבה לא ידועה")}
    return {"status": "pending", "output_url": "", "error": ""}


def apply_lip_sync(
    video_url: str,
    audio_url: str,
    model: str = "sync-2",
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Submit a lip-sync job and return the URL of the synced video.

    Called from the worker process (not from HTTP handlers).
    Sync failure should be caught by the caller — it must not cancel the Kling video.

    Args:
        video_url: URL of the generated (silent or audio) video from Kling.
        audio_url: URL of the dialogue audio file (MP3 or WAV).
        model: Sync.so model — sync-2 (fast) or sync-3 (highest quality).
        sleep: injectable for testing.

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
            raise RuntimeError(f"Sync.so כשל בסנכרון: {result['error']}")
    raise TimeoutError(
        f"Sync.so לא השלים את הסנכרון אחרי {_MAX_POLLS * _POLL_INTERVAL} שניות."
    )


def check_sync_connection() -> dict:
    """Validate Sync.so API key without submitting a real job."""
    if not settings.sync_api_key:
        return {
            "connected": False,
            "status": "not_configured",
            "message": "SYNC_API_KEY אינו מוגדר.",
        }
    url = f"{settings.sync_api_base}/v2/generate/probe-ai-film-os"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=_headers())
    except httpx.RequestError as exc:
        return {
            "connected": False,
            "status": "network_error",
            "message": f"לא ניתן להגיע ל-Sync.so: {exc.__class__.__name__}",
        }
    if resp.status_code in {200, 404}:
        return {"connected": True, "status": "connected", "message": "Sync.so מחובר."}
    if resp.status_code in {401, 403}:
        return {
            "connected": False,
            "status": "invalid_key",
            "message": "Sync.so דחה את מפתח ה-API.",
        }
    return {
        "connected": False,
        "status": "provider_error",
        "message": f"Sync.so החזיר תגובה לא צפויה: {resp.status_code}",
    }
