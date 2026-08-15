"""Kling AI video provider adapter for AI Film OS.

Translates AI-Film-OS VideoGenerationRequest into Kling image-to-video API calls.

Submit + check-task pattern keeps the worker non-blocking:
  task_id = provider.submit(request)   # fast POST, returns immediately
  status  = provider.check_task(id)    # single GET, no sleep

Authentication follows the documented Kling open-platform model: an
AccessKey/SecretKey pair signs a short-lived HS256 JWT that is sent as
``Authorization: Bearer <token>``. There is no long-lived bearer API key.
The JWT carries ``iss`` (AccessKey), ``exp`` (now + 30 min) and ``nbf``
(now - 5 s, absorbing clock skew), and is minted per request so no token
is cached, logged or persisted.

Redaction contract: provider response bodies, signed media URLs, prompts
and credentials never appear in exception messages. Errors carry only the
HTTP status, the documented numeric ``code`` and the ``request_id``
correlation identifier, which are safe to surface to operators.

Environment variables required:
    KLING_ACCESS_KEY    — Kling AccessKey from https://app.klingai.com
    KLING_SECRET_KEY    — Kling SecretKey (signs the JWT; never transmitted)
    KLING_API_BASE      — optional override (default: https://api-singapore.klingai.com)
    KLING_DEFAULT_MODEL — optional model override (default: kling-v2-master)
"""

import base64
import hashlib
import hmac
import json
import re
import time

import httpx

from app.core.config import settings
from app.services.video_provider import (
    VideoGenerationRequest,
    VideoProviderNotConfigured,
)

# Token lifetime documented by Kling: 30 minutes, with a small negative
# not-before offset so minor clock drift cannot reject a fresh token.
JWT_TTL_SECONDS = 1800
JWT_NBF_SKEW_SECONDS = 5

# Model identifiers accepted by the Kling image2video endpoint.
SUPPORTED_MODELS = frozenset(
    {
        "kling-v1",
        "kling-v1-5",
        "kling-v1-6",
        "kling-v2-master",
        "kling-v2-1",
        "kling-v2-1-master",
        "kling-v2-5-turbo",
        "kling-v2-6",
    }
)

_FALLBACK_MODEL = "kling-v2-master"

_PROFILE_TO_MODEL = {
    "fast": "kling-v2-5-turbo",
    "cinematic": "kling-v2-master",
    "high_fidelity": "kling-v2-6",
    "auto": "kling-v2-master",
}

# Kling accepts only these two clip lengths, encoded as strings.
_SUPPORTED_DURATIONS = ("5", "10")

# Documented predefined camera movements. Anything expressible as a simple
# axis movement is sent as {"type": "simple", "config": {...}} instead.
_PREDEFINED_CAMERA_TYPES = frozenset(
    {"down_back", "forward_up", "right_turn_forward", "left_turn_forward"}
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def encode_jwt(access_key: str, secret_key: str, *, now: int | None = None) -> str:
    """Sign a short-lived HS256 JWT for the Kling open platform.

    Signing only — this never parses or verifies untrusted tokens, so the
    algorithm-confusion class of JWT bugs does not apply. The SecretKey is
    used as the HMAC key and is never placed in the token or transmitted.
    """
    issued_at = int(time.time()) if now is None else int(now)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": access_key,
        "exp": issued_at + JWT_TTL_SECONDS,
        "nbf": issued_at - JWT_NBF_SKEW_SECONDS,
    }
    segments = [
        _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(signature))
    return ".".join(segments)


def _require_credentials() -> tuple[str, str]:
    access_key = settings.kling_access_key
    secret_key = settings.kling_secret_key
    if not access_key or not secret_key:
        raise VideoProviderNotConfigured(
            "KLING_ACCESS_KEY ו-KLING_SECRET_KEY אינם מוגדרים. "
            "הגדר את שני המפתחות בסביבת ההפעלה."
        )
    return access_key, secret_key


def _headers() -> dict:
    """Build request headers with a freshly minted, short-lived JWT."""
    access_key, secret_key = _require_credentials()
    return {
        "Authorization": f"Bearer {encode_jwt(access_key, secret_key)}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "AI-Film-OS/1.0",
    }


def _model_for(profile: str) -> str:
    model = _PROFILE_TO_MODEL.get(profile)
    if model:
        return model
    configured = settings.kling_default_model
    return configured if configured in SUPPORTED_MODELS else _FALLBACK_MODEL


def _duration_for(duration_seconds: float) -> str:
    """Snap an arbitrary clip length onto a supported Kling duration."""
    try:
        requested = float(duration_seconds)
    except (TypeError, ValueError):
        return _SUPPORTED_DURATIONS[0]
    return "10" if requested > 7.5 else "5"


def _camera_motion_to_kling(camera_motion: str) -> dict | None:
    """Map a shot's camera motion onto a documented camera_control block.

    Returns None when no motion was requested, in which case camera_control
    is omitted entirely rather than sent as an undocumented "static" value.
    """
    motion = (camera_motion or "").lower()
    if not motion.strip():
        return None
    simple = {
        "zoom": {"zoom": 5},
        "pan": {"pan": -5},
        "tilt": {"tilt": 5},
        "crane": {"vertical": 5},
        "drone": {"vertical": 5},
        "truck": {"horizontal": 5},
        "roll": {"roll": 5},
    }
    predefined = {
        "orbit": "left_turn_forward",
        "tracking": "forward_up",
        "dolly": "forward_up",
        "pull": "down_back",
    }
    for key, camera_type in predefined.items():
        if key in motion:
            return {"type": camera_type}
    for key, config in simple.items():
        if key in motion:
            return {"type": "simple", "config": dict(config)}
    return None


def _estimate_cost(duration_seconds: float, model: str) -> float:
    rates = {
        "kling-v1": 0.020,
        "kling-v1-5": 0.026,
        "kling-v1-6": 0.030,
        "kling-v2-master": 0.045,
        "kling-v2-1": 0.038,
        "kling-v2-1-master": 0.050,
        "kling-v2-5-turbo": 0.028,
        "kling-v2-6": 0.065,
    }
    rate = rates.get(model, 0.045)
    return round(rate * max(duration_seconds / 5, 1), 4)


def _safe_request_id(body: object) -> str:
    """Extract only the non-sensitive request_id correlation identifier."""
    if not isinstance(body, dict):
        return ""
    request_id = body.get("request_id")
    if isinstance(request_id, str) and _REQUEST_ID_RE.match(request_id):
        return request_id
    return ""


def _decode_envelope(resp: httpx.Response) -> dict:
    """Parse the documented {code, message, request_id, data} envelope.

    Never echoes the raw body: a malformed payload raises with the HTTP
    status only.
    """
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Kling החזיר תשובה שאינה JSON תקין (HTTP {resp.status_code})."
        ) from exc
    if not isinstance(body, dict):
        raise RuntimeError(
            f"Kling החזיר מבנה תשובה לא צפוי (HTTP {resp.status_code})."
        )
    return body


def _raise_for_status(resp: httpx.Response, stage: str) -> dict:
    """Convert transport and envelope errors into redacted exceptions."""
    if resp.status_code in {401, 403}:
        raise VideoProviderNotConfigured(
            "Kling דחה את פרטי ההזדהות. יש לעדכן את KLING_ACCESS_KEY ו-KLING_SECRET_KEY."
        )
    if resp.status_code not in {200, 201, 202}:
        request_id = _safe_request_id(_safe_json(resp))
        suffix = f" (request_id={request_id})" if request_id else ""
        raise RuntimeError(f"Kling {stage} נכשל עם HTTP {resp.status_code}{suffix}.")

    body = _decode_envelope(resp)
    code = body.get("code")
    if code not in (0, None):
        request_id = _safe_request_id(body)
        suffix = f", request_id={request_id}" if request_id else ""
        raise RuntimeError(f"Kling {stage} נכשל (code={code}{suffix}).")
    return body


def _safe_json(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        return None


class KlingProvider:
    name = "kling"

    def submit(self, request: VideoGenerationRequest) -> str:
        """POST to Kling, return task_id immediately — no polling, no sleep."""
        headers = _headers()

        model = _model_for(request.model_profile)
        payload = {
            "model_name": model,
            "image": request.image_url,
            "prompt": request.prompt,
            "duration": _duration_for(request.duration_seconds),
            "mode": "pro" if request.model_profile == "high_fidelity" else "std",
            "cfg_scale": 0.5,
        }
        camera_control = _camera_motion_to_kling(request.camera_motion)
        if camera_control is not None:
            payload["camera_control"] = camera_control

        url = f"{settings.kling_api_base}/v1/videos/image2video"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)

        body = _raise_for_status(resp, "שליחת המשימה")
        data = body.get("data")
        task_id = data.get("task_id") if isinstance(data, dict) else None
        if not task_id or not isinstance(task_id, str):
            request_id = _safe_request_id(body)
            suffix = f" (request_id={request_id})" if request_id else ""
            raise RuntimeError(f"Kling לא החזיר task_id{suffix}.")
        return task_id

    def check_task(self, task_id: str) -> dict:
        """Single GET to check Kling task status — no sleep.

        Returns:
            {"status": "pending"|"succeed"|"failed", "url": str, "reason": str}
        """
        headers = _headers()
        url = f"{settings.kling_api_base}/v1/videos/image2video/{task_id}"
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=headers)

        body = _raise_for_status(resp, "בדיקת סטטוס")
        data = body.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Kling החזיר מבנה סטטוס לא צפוי.")

        status = data.get("task_status", "")
        if status == "succeed":
            task_result = data.get("task_result")
            videos = task_result.get("videos") if isinstance(task_result, dict) else None
            video_url = ""
            if isinstance(videos, list) and videos and isinstance(videos[0], dict):
                video_url = str(videos[0].get("url") or "")
            if not video_url:
                raise RuntimeError("Kling דיווח על הצלחה אבל לא החזיר URL לווידאו.")
            return {"status": "succeed", "url": video_url, "reason": ""}
        if status == "failed":
            # task_status_msg is provider-authored free text; it is not
            # surfaced verbatim so provider payloads never reach logs.
            return {"status": "failed", "url": "", "reason": "Kling דיווח על כישלון במשימה."}
        if status in {"submitted", "processing"}:
            return {"status": "pending", "url": "", "reason": ""}
        raise RuntimeError("Kling החזיר סטטוס משימה לא מוכר.")

    def cost_for(self, request: VideoGenerationRequest) -> float:
        model = _model_for(request.model_profile)
        return _estimate_cost(request.duration_seconds, model)
