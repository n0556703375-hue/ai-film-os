"""API endpoints for background worker management and debugging."""

import httpx
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/api/worker", tags=["worker"])


@router.get("/status")
def get_worker_status():
    """Get the status of the background worker thread.

    Returns:
        {
            "alive": bool - is the worker thread running?
            "thread_id": int or null - OS thread ID
            "last_job_timestamp": string or null - ISO timestamp of last processed job
            "last_job_shot_id": int or null - shot ID of last processed job
            "jobs_processed": int - total jobs processed by this thread
            "queued_job_count": int - jobs waiting in queue
        }
    """
    from app import background_worker

    return background_worker.get_status()


@router.post("/process-next")
def trigger_next_job():
    """Manually trigger processing of the next queued job.

    Useful for debugging and immediate testing. The background thread
    continues processing independently.

    Returns:
        The result of process_one_job(), or {} if no job was queued.
    """
    from app import background_worker

    return background_worker.process_next_job()


@router.get("/test-fal-connection")
def test_fal_connection():
    """Debug endpoint: verify the configured FAL_API_KEY authenticates with fal.ai.

    Never returns the full key — only its first 8 characters, so the exact
    key Render is using can be compared against the fal.ai dashboard without
    exposing the credential.

    Returns:
        {
            "key_prefix": str - first 8 chars of FAL_API_KEY, "" if unset
            "http_status": int or null - status code from fal.ai, null if the
                request could not be made at all (no key, network error)
            "connected": bool - true only on an HTTP 200 response
        }
    """
    key = settings.fal_api_key.strip()
    key_prefix = key[:8]

    if not key:
        return {"key_prefix": "", "http_status": None, "connected": False}

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                "https://fal.ai/api/models",
                headers={"Authorization": f"Key {key}"},
            )
        return {
            "key_prefix": key_prefix,
            "http_status": resp.status_code,
            "connected": resp.status_code == 200,
        }
    except httpx.RequestError:
        return {"key_prefix": key_prefix, "http_status": None, "connected": False}
