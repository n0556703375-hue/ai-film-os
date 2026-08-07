"""Seedance 2.0 video provider adapter for AI Film OS via fal.ai.

Environment variables required:
    FAL_API_KEY             — fal.ai API key from https://fal.ai/dashboard
    FAL_SEEDANCE_MODEL      — optional override (default: bytedance/seedance-2.0/image-to-video)
    FAL_SEEDANCE_FAST_MODEL — fast tier (default: bytedance/seedance-2.0/fast/image-to-video)

The provider intentionally delegates submit/poll/result URL handling to fal.ai's
official Python client instead of reconstructing queue URLs manually.
"""

import os

import fal_client

from app.core.config import settings
from app.services.video_provider import (
    VideoGenerationRequest,
    VideoGenerationResult,
    VideoProviderNotConfigured,
)

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
            url = first.get("url")
            if url:
                return url
        elif first:
            return str(first)
    raise RuntimeError("fal.ai returned a completed response without a video URL")


class SeedanceProvider:
    """Seedance 2.0 via fal.ai's official Python client."""

    name = "seedance"

    def __init__(self):
        key = settings.fal_api_key.strip()
        if not key:
            raise VideoProviderNotConfigured("FAL_API_KEY not set.")

        # fal-client reads FAL_KEY. Copy the already server-side Render secret
        # into the SDK's expected environment variable without logging it.
        os.environ["FAL_KEY"] = key

    def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        """Submit a video generation request and wait for the official client result."""
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

        try:
            handler = fal_client.submit(model, arguments=payload)
            request_id = str(getattr(handler, "request_id", "") or "")
            if not request_id:
                raise RuntimeError("fal.ai submission did not return request_id")
            result_body = handler.get()
        except VideoProviderNotConfigured:
            raise
        except Exception as exc:
            # Keep provider response bodies, signed URLs, and credentials out of
            # application-visible errors while preserving a stable failure class.
            raise RuntimeError("fal.ai generation failed via official client") from exc

        if not isinstance(result_body, dict):
            raise RuntimeError("fal.ai returned an invalid completed response")

        video_url = _extract_video_url(result_body)
        cost = _estimate_cost(request.duration_seconds, model)

        return VideoGenerationResult(
            url=video_url,
            provider="seedance",
            model=model,
            external_task_id=request_id,
            actual_cost_usd=cost,
        )
