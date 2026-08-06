"""Kling AI video provider adapter for AI Film OS.

Translates AI-Film-OS VideoGenerationRequest into Kling image-to-video API calls.

Submit + check-task pattern keeps the worker non-blocking:
  task_id = provider.submit(request)   # fast POST, returns immediately
  status  = provider.check_task(id)    # single GET, no sleep

Environment variables required:
    KLING_API_KEY   — Kling API key from https://platform.klingai.com
    KLING_API_BASE  — optional override (default: https://api.klingai.com)
    KLING_DEFAULT_MODEL — optional model override (default: kling-v3)
"""

import httpx

from app.core.config import settings
from app.services.video_provider import (
    VideoGenerationRequest,
    VideoProviderNotConfigured,
)

_PROFILE_TO_MODEL = {
    "fast": "kling-v2",
    "cinematic": "kling-v3",
    "high_fidelity": "kling-v3-omni",
    "auto": "kling-v3",
}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.kling_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "AI-Film-OS/1.0",
    }


def _model_for(profile: str) -> str:
    return _PROFILE_TO_MODEL.get(profile, settings.kling_default_model)


def _camera_motion_to_kling(camera_motion: str) -> str:
    motion = camera_motion.lower()
    mapping = {
        "tracking": "move_forward",
        "orbit": "orbit_left",
        "crane": "move_up",
        "drone": "move_up",
        "handheld": "shake",
        "zoom": "zoom_in",
        "pan": "pan_left",
        "tilt": "tilt_up",
    }
    for key, val in mapping.items():
        if key in motion:
            return val
    return "static"


def _estimate_cost(duration_seconds: float, model: str) -> float:
    rates = {
        "kling-v2": 0.028,
        "kling-v3": 0.045,
        "kling-v3-omni": 0.065,
    }
    rate = rates.get(model, 0.045)
    return round(rate * max(duration_seconds / 5, 1), 4)


class KlingProvider:
    name = "kling"

    def submit(self, request: VideoGenerationRequest) -> str:
        """POST to Kling, return task_id immediately — no polling, no sleep."""
        if not settings.kling_api_key:
            raise VideoProviderNotConfigured(
                "KLING_API_KEY אינו מוגדר. הגדר את המפתח בסביבת ההפעלה."
            )

        model = _model_for(request.model_profile)
        payload = {
            "model": model,
            "image_url": request.image_url,
            "prompt": request.prompt,
            "duration": int(min(max(request.duration_seconds, 5), 15)),
            "aspect_ratio": request.aspect_ratio or "16:9",
            "camera_control": {"type": _camera_motion_to_kling(request.camera_motion)},
            "cfg_scale": 0.5,
        }
        if request.audio_mode == "dialogue":
            payload["with_audio"] = True

        url = f"{settings.kling_api_base}/v1/videos/image2video"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=_headers())

        if resp.status_code == 401:
            raise VideoProviderNotConfigured(
                "Kling דחה את מפתח ה-API. יש לעדכן את KLING_API_KEY."
            )
        if resp.status_code not in {200, 201, 202}:
            raise RuntimeError(
                f"Kling החזיר שגיאה {resp.status_code}: {resp.text[:300]}"
            )

        body = resp.json()
        task_id = body.get("data", {}).get("task_id") or body.get("task_id")
        if not task_id:
            raise RuntimeError(f"Kling לא החזיר task_id: {resp.text[:300]}")
        return task_id

    def check_task(self, task_id: str) -> dict:
        """Single GET to check Kling task status — no sleep.

        Returns:
            {"status": "pending"|"succeed"|"failed", "url": str, "reason": str}
        """
        url = f"{settings.kling_api_base}/v1/videos/image2video/{task_id}"
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=_headers())
        if resp.status_code != 200:
            raise RuntimeError(
                f"Kling polling שגיאה {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json().get("data", {})
        status = data.get("task_status", "")
        if status == "succeed":
            videos = data.get("task_result", {}).get("videos", [])
            if not videos:
                raise RuntimeError("Kling דיווח על הצלחה אבל לא החזיר URL לווידאו.")
            return {"status": "succeed", "url": videos[0]["url"], "reason": ""}
        if status == "failed":
            reason = data.get("task_status_msg", "סיבה לא ידועה")
            return {"status": "failed", "url": "", "reason": reason}
        return {"status": "pending", "url": "", "reason": ""}
