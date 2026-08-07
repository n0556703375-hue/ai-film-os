"""Seedance 2.0 video provider adapter for AI Film OS via fal.ai.

Environment variables required:
    FAL_API_KEY             — fal.ai API key from https://fal.ai/dashboard
    FAL_SEEDANCE_MODEL      — optional override (default: bytedance/seedance-2.0/image-to-video)
    FAL_SEEDANCE_FAST_MODEL — fast tier (default: bytedance/seedance-2.0/image-to-video-fast)
    FAL_API_BASE            — optional base URL (default: https://queue.fal.run)
"""

import time
import httpx
from app.core.config import settings
from app.services.video_provider import (
    VideoGenerationRequest,
    VideoGenerationResult,
    VideoProviderNotConfigured,
)

_POLL_INTERVAL = 8
_MAX_POLLS = 112

_CAMERA_MOTION_PHRASES = {
    "tracking": "smooth tracking shot following the subject",
    "orbit": "orbital camera movement around the subject",
    "crane": "crane shot moving upward",
    "drone": "aerial drone shot rising",
    "handheld": "handheld camera with subtle natural movement",
    "zoom": "slow cinematic zoom",
    "pan": "gentle horizontal pan",
    "tilt": "slow vertical tilt",
    "dolly": "dolly zoom pushing in",
    "static": "static locked-off camera",
}

_COST_PER_SECOND = {
    "bytedance/seedance-2.0/image-to-video": 0.045,
    "bytedance/seedance-2.0/image-to-video-fast": 0.025,
}


def _camera_phrase(camera_motion: str) -> str:
    motion = camera_motion.lower()
    for key, phrase in _CAMERA_MOTION_PHRASES.items():
        if key in motion:
            return phrase
    return ""


def _build_prompt(request: VideoGenerationRequest) -> str:
    parts = [request.prompt.strip()]
    cam = _camera_phrase(request.camera_motion)
    if cam:
        parts.append(cam)
    return ". ".join(p for p in parts if p)


def _model_for(profile: str) -> str:
    if profile == "fast":
        return settings.fal_seedance_fast_model
    return settings.fal_seedance_model


def _headers() -> dict:
    return {
        "Authorization": f"Key {settings.fal_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "AI-Film-OS/1.0",
    }


def _estimate_cost(duration_seconds: float, model: str) -> float:
    rate = _COST_PER_SECOND.get(model, 0.045)
    return round(rate * max(duration_seconds, 5), 4)


def _extract_video_url(body: dict) -> str:
    video = body.get("video")
    if isinstance(video, dict):
        url = video.get("url")
        if url:
            return url
    if isinstance(video, str):
        return video
    url = body.get("url") or body.get("video_url")
    if url:
        return url
    videos = body.get("videos")
    if isinstance(videos, list) and videos:
        first = videos[0]
        if isinstance(first, dict):
            return first.get("url", "")
        return str(first)
    raise RuntimeError(f"fal.ai לא החזיר URL לווידאו. תגובה: {str(body)[:300]}")


def _poll_until_complete(model: str, request_id: str) -> str:
    status_url = f"{settings.fal_api_base}/{model}/requests/{request_id}/status"
    result_url = f"{settings.fal_api_base}/{model}/requests/{request_id}"
    for _ in range(_MAX_POLLS):
        time.sleep(_POLL_INTERVAL)
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(status_url, headers=_headers())
        if resp.status_code != 200:
            raise RuntimeError(f"fal.ai polling שגיאה {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        status = data.get("status", "")
        if status == "COMPLETED":
            with httpx.Client(timeout=20.0) as client:
                result_resp = client.get(result_url, headers=_headers())
            if result_resp.status_code != 200:
                raise RuntimeError(f"fal.ai result fetch שגיאה {result_resp.status_code}: {result_resp.text[:200]}")
            return _extract_video_url(result_resp.json())
        if status == "FAILED":
            error_msg = data.get("error") or data.get("message") or "Unknown error"
            raise RuntimeError(f"fal.ai קידוד נכשל: {str(error_msg)[:200]}")
    raise TimeoutError(f"fal.ai לא השלים את יצירת הווידאו אחרי {_POLL_INTERVAL * _MAX_POLLS:.0f} שניות.")


class SeedanceProvider:
    """Seedance 2.0 via fal.ai queue API."""

    name = "seedance"

    def __init__(self):
        if not settings.fal_api_key:
            raise VideoProviderNotConfigured("FAL_API_KEY not set.")

    def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        """Submit a video generation request and wait for completion."""
        model = _model_for(request.model_profile)

        payload = {
            "image_url": request.image_url,
            "prompt": _build_prompt(request),
            "duration": int(max(1, min(10, request.duration_seconds))),
            "height": 1080,
            "width": 1920,
        }

        if request.aspect_ratio:
            try:
                w, h = map(int, request.aspect_ratio.split(":"))
                if w > 0 and h > 0:
                    payload["width"] = w
                    payload["height"] = h
            except (ValueError, AttributeError):
                pass

        with httpx.Client(timeout=20.0) as client:
            submit_url = f"{settings.fal_api_base}/{model}"
            resp = client.post(submit_url, json=payload, headers=_headers())

        if resp.status_code not in {200, 202}:
            raise RuntimeError(f"fal.ai submission שגיאה {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError(f"fal.ai לא החזיר request_id. תגובה: {str(data)[:300]}")

        video_url = _poll_until_complete(model, request_id)
        cost = _estimate_cost(request.duration_seconds, model)

        return VideoGenerationResult(
            url=video_url,
            provider="seedance",
            model=model,
            external_task_id=request_id,
            actual_cost_usd=cost,
        )
