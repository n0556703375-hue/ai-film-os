import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories import jobs, shots
from app.services.public_media_url import PublicMediaUrlError, normalize_public_media_url, preflight_check_public_image
from app.services.video_model_selector import select_video_model
from app.services.video_provider import DisabledVideoProvider, VideoProviderNotConfigured, get_video_provider


router = APIRouter(prefix="/api/video-generation", tags=["video-generation"])


class VideoQueueRequest(BaseModel):
    duration_seconds: float = Field(default=5, ge=1, le=30)
    camera_motion: str = Field(default="", max_length=1000)
    audio_mode: Literal["none", "ambient", "dialogue", "music"] = "none"
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    model_hint: Literal["auto", "cinematic", "fast", "high_fidelity"] = "auto"
    instructions: str = Field(default="", max_length=5000)


class ConfirmedRetryRequest(BaseModel):
    confirmed: Literal[True]


def _approved_image(shot_id: int) -> dict | None:
    return next(
        (
            media
            for media in shots.list_media_results(shot_id)
            if media.get("media_type") == "image" and media.get("status") == "מאושר"
        ),
        None,
    )


def _job_key(shot: dict, image: dict, request: VideoQueueRequest) -> str:
    identity = {
        "shot_id": shot["id"],
        "image_media_id": image["id"],
        "prompt": shot.get("prompt", ""),
        **request.model_dump(),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"shot:{shot['id']}:video:{digest}"


def _normalized_video_job_status(job: dict) -> dict:
    status = job["status"]
    terminal = status in jobs.TERMINAL_STATUSES
    retryable = status in {"queued", "running", "retrying"}
    attempts = int(job.get("attempts") or 0)
    max_attempts = int(job.get("max_attempts") or 0)
    return {
        "job_id": job["id"],
        "shot_id": job["shot_id"],
        "status": status,
        "terminal": terminal,
        "retryable": retryable,
        "attempts": attempts,
        "max_attempts": max_attempts,
        "attempts_remaining": max(max_attempts - attempts, 0),
        "updated_at": job.get("updated_at"),
        "finished_at": job.get("finished_at"),
    }


@router.get("/shots/{shot_id}/readiness")
def get_shot_readiness(shot_id: int):
    """Report whether a shot is ready for Generate Video — never submits to the provider.

    Every check here is read-only / non-billing: the approved-image lookup,
    the public-URL preflight (a bounded reachability fetch, not a fal.ai
    submission), instantiating the configured provider (which only reads
    env vars), and checking the background worker thread's liveness. The UI
    calls this before enabling the Generate Video button so a doomed
    submission never happens in the first place.
    """
    shot = shots.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")

    reasons: list[str] = []

    image = _approved_image(shot_id)
    approved_image = image is not None
    if not approved_image:
        reasons.append("no_approved_image")

    image_publicly_accessible = False
    if approved_image:
        try:
            public_url = normalize_public_media_url(image["url"])
            preflight_check_public_image(public_url)
            image_publicly_accessible = True
        except PublicMediaUrlError as exc:
            reasons.append(f"image_not_publicly_accessible:{exc.reason}")

    provider_configured = False
    try:
        provider = get_video_provider()
        provider_configured = not isinstance(provider, DisabledVideoProvider)
    except VideoProviderNotConfigured:
        provider_configured = False
    if not provider_configured:
        reasons.append("provider_not_configured")

    from app import background_worker

    worker_alive = background_worker.is_alive()
    if not worker_alive:
        reasons.append("worker_not_alive")

    ready = approved_image and image_publicly_accessible and provider_configured and worker_alive

    return {
        "ready": ready,
        "approved_image": approved_image,
        "image_publicly_accessible": image_publicly_accessible,
        "provider_configured": provider_configured,
        "worker_alive": worker_alive,
        "reasons": reasons,
    }


@router.post("/shots/{shot_id}/queue")
def queue_video(shot_id: int, request: VideoQueueRequest):
    shot = shots.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")
    image = _approved_image(shot_id)
    if not image:
        raise HTTPException(409, "יש לאשר תמונת שוט לפני יצירת וידאו.")

    versions = shots.list_prompt_versions(shot_id)
    prompt_version_id = versions[0]["id"] if versions else None
    request_data = request.model_dump()
    model_profile = select_video_model(shot, request_data)
    payload = {
        "prompt": shot.get("prompt", ""),
        "prompt_version_id": prompt_version_id,
        "source_image_media_id": image["id"],
        "duration_seconds": request.duration_seconds,
        "camera_motion": request.camera_motion or shot.get("movement", ""),
        "audio_mode": request.audio_mode,
        "aspect_ratio": request.aspect_ratio,
        "model_hint": request.model_hint,
        "selected_model_profile": model_profile.profile,
        "model_selection_reason": model_profile.reason,
        "instructions": request.instructions,
    }
    job, created = jobs.enqueue_job(
        shot["project_id"],
        shot_id,
        "video",
        payload,
        _job_key(shot, image, request),
        max_attempts=3,
    )
    return {
        "created": created,
        "media_type": "video",
        "selected_model_profile": model_profile.profile,
        "model_selection_reason": model_profile.reason,
        "job": job,
    }


@router.get("/jobs/{job_id}/status")
def get_video_job_status(job_id: int):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "משימת הווידאו לא נמצאה.")
    if job.get("job_type") != "video":
        raise HTTPException(409, "המשימה אינה משימת וידאו.")
    return _normalized_video_job_status(job)


@router.post("/jobs/{job_id}/retry")
def retry_video_job(job_id: int, request: ConfirmedRetryRequest):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "משימת הווידאו לא נמצאה.")
    if job.get("job_type") != "video":
        raise HTTPException(409, "המשימה אינה משימת וידאו.")
    try:
        retried = jobs.retry_failed_job(job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return _normalized_video_job_status(retried)
