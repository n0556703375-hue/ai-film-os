import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories import jobs, shots

router = APIRouter(prefix="/api/video-generation", tags=["video-generation"])


class VideoQueueRequest(BaseModel):
    duration_seconds: float = Field(default=5, ge=1, le=30)
    camera_motion: str = Field(default="", max_length=1000)
    audio_mode: Literal["none", "ambient", "dialogue", "music"] = "none"
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    model_hint: Literal["auto", "cinematic", "fast", "high_fidelity"] = "auto"
    instructions: str = Field(default="", max_length=5000)


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
    payload = {
        "prompt": shot.get("prompt", ""),
        "prompt_version_id": prompt_version_id,
        "source_image_media_id": image["id"],
        "duration_seconds": request.duration_seconds,
        "camera_motion": request.camera_motion or shot.get("movement", ""),
        "audio_mode": request.audio_mode,
        "aspect_ratio": request.aspect_ratio,
        "model_hint": request.model_hint,
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
    return {"created": created, "media_type": "video", "job": job}
