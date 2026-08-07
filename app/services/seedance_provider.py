"""Seedance 2.0 video provider adapter for AI Film OS via fal.ai.

Environment variables required:
    FAL_API_KEY             — fal.ai API key from https://fal.ai/dashboard
    FAL_SEEDANCE_MODEL      — optional override (default: bytedance/seedance-2.0/image-to-video)
    FAL_SEEDANCE_FAST_MODEL — fast tier (default: bytedance/seedance-2.0/fast/image-to-video)
    FAL_API_BASE            — optional base URL (default: https://queue.fal.run)
"""

import time
from urllib.parse import urlparse, urlunparse

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
    "bytedance/seedance-2.0/fast/image-to-video": 0.025,
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
        "Authorization": f"Key {settings.fal_api_key.strip()}",
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
    raise RuntimeError("fal.ai returned a completed response without a video URL")


def _queue_url(value: object, fallback: str) -> str:
    """Use fal's returned queue URL only when it stays on the configured queue host."""
    candidate = value.strip() if isinstance(value, str) else ""
    if not candidate:
        return fallback

    parsed = urlparse(candidate)
    base = urlparse(settings.fal_api_base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname != base.hostname:
        raise RuntimeError("fal.ai returned an invalid queue URL")
    return candidate


def _result_url(response_url: object, fallback: str) -> str:
    """Convert fal's convenience /response URL to the documented REST result URL."""
    candidate = _queue_url(response_url, fallback)
    parsed = urlparse(candidate)
    path = parsed.path.rstrip("/")
    if path.endswith("/response"):
        path = path[: -len("/response")]
    return urlunparse(parsed._replace(path=path))


def _poll_until_complete(status_url: str, result_url: str) -> str:
    for _ in range(_MAX_POLLS):
        time.sleep(_POLL_INTERVAL)
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(status_url, headers=_headers())
        if resp.status_code != 200:
            raise RuntimeError(f"fal.ai polling failed with HTTP {resp.status_code}")

        data = resp.json()
        status = data.get("status", "")
        if status in {"IN_QUEUE", "IN_PROGRESS"}:
            continue
        if status == "COMPLETED":
            if data.get("error") or data.get("error_type"):
                raise RuntimeError("fal.ai generation failed")
            with httpx.Client(timeout=20.0) as client:
                result_resp = client.get(result_url, headers=_headers())
            if result_resp.status_code != 200:
                raise RuntimeError(f"fal.ai result fetch failed with HTTP {result_resp.status_code}")
            return _extract_video_url(result_resp.json())
        raise RuntimeError("fal.ai returned an unknown queue status")

    raise TimeoutError(
        f"fal.ai did not complete video generation within {_POLL_INTERVAL * _MAX_POLLS:.0f} seconds"
    )


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
            raise RuntimeError(f"fal.ai submission failed with HTTP {resp.status_code}")

        data = resp.json()
        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError("fal.ai submission did not return request_id")

        fallback_status_url = (
            f"{settings.fal_api_base}/{model}/requests/{request_id}/status"
        )
        fallback_result_url = (
            f"{settings.fal_api_base}/{model}/requests/{request_id}"
        )
        status_url = _queue_url(data.get("status_url"), fallback_status_url)
        result_url = _result_url(data.get("response_url"), fallback_result_url)

        video_url = _poll_until_complete(status_url, result_url)
        cost = _estimate_cost(request.duration_seconds, model)

        return VideoGenerationResult(
            url=video_url,
            provider="seedance",
            model=model,
            external_task_id=request_id,
            actual_cost_usd=cost,
        )
