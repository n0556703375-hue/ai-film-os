from urllib.parse import urlparse

from app.repositories import shots


def _result_url(result: dict) -> str:
    url = str(result.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("תוצאת וידאו שהושלמה חייבת לכלול כתובת HTTPS תקינה.")
    return url


def ingest_completed_video_job(job: dict, result: dict) -> dict:
    """Store one draft media version for a completed video job.

    Repeated completion callbacks are idempotent by generation job id and never
    replace or approve an existing media result.
    """
    if job.get("job_type") != "video":
        raise ValueError("המשימה אינה משימת וידאו.")

    job_id = int(job["id"])
    shot_id = int(job["shot_id"])
    for media in shots.list_media_results(shot_id):
        metadata = media.get("metadata") or {}
        if media.get("media_type") == "video" and metadata.get("generation_job_id") == job_id:
            return media

    payload = job.get("payload") or {}
    metadata = {
        "generation_job_id": job_id,
        "source_image_media_id": payload.get("source_image_media_id"),
        "selected_model_profile": payload.get("selected_model_profile"),
        "model_selection_reason": payload.get("model_selection_reason"),
        "duration_seconds": payload.get("duration_seconds"),
        "camera_motion": payload.get("camera_motion"),
        "audio_mode": payload.get("audio_mode"),
        "aspect_ratio": payload.get("aspect_ratio"),
    }
    return shots.create_media_result(
        shot_id,
        {
            "media_type": "video",
            "url": _result_url(result),
            "provider": str(result.get("provider") or ""),
            "model": str(result.get("model") or payload.get("selected_model_profile") or ""),
            "prompt_version_id": payload.get("prompt_version_id"),
            "status": "טיוטה",
            "notes": str(result.get("notes") or ""),
            "metadata": metadata,
        },
    )
