"""Seedance 2.0 video provider adapter for AI Film OS via fal.ai.

Environment variables required:
    FAL_API_KEY             — fal.ai API key from https://fal.ai/dashboard
    FAL_SEEDANCE_MODEL      — optional override (default: bytedance/seedance-2.0/image-to-video)
    FAL_SEEDANCE_FAST_MODEL — fast tier (default: bytedance/seedance-2.0/fast/image-to-video)

The provider delegates submit/poll/result handling to fal.ai's official Python
client and sends only fields accepted by the current Seedance 2.0 schema.

Resumability
------------
``submit()`` performs only the queue submission and returns immediately; it
never blocks waiting for the video. The caller (app.worker) persists the
returned task id to ``media_jobs.provider_task_id`` before any polling starts,
then polls via ``check_task()`` — a single, non-blocking status check per
call. This mirrors the Kling provider's contract so a worker crash, restart,
or retryable failure mid-poll resumes the *same* fal.ai request instead of
submitting a new (separately billed) one. Never call fal.ai's blocking
``handler.get()``/``fal_client.subscribe`` here for that reason.

Redaction contract
-------------------
Nothing this module raises, returns, or logs may carry provider response
bodies, API keys, or signed URLs. Failures are reported as a stable category
from ``SeedanceErrorCategory`` plus, at most, a numeric HTTP status.
"""

import ipaddress
import os
from urllib.parse import urlparse

import fal_client

from app.core.config import settings
from app.services.video_provider import (
    VideoGenerationRequest,
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

_ALLOWED_ASPECT_RATIOS = {"auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}

# fal.ai Seedance 2.0 720p rates at the time this integration was updated.
_COST_PER_SECOND = {
    "bytedance/seedance-2.0/image-to-video": 0.3034,
    "bytedance/seedance-2.0/fast/image-to-video": 0.2419,
}

# Separates the fal.ai model id from the request id inside the opaque
# provider_task_id string persisted on media_jobs. fal.ai's queue status/result
# endpoints require the model id to build the request URL, so it must travel
# with the request id to survive a worker restart.
_TASK_ID_SEPARATOR = "::"


class SeedanceErrorCategory:
    """Stable, sanitized failure categories safe for logs and persistence."""

    AUTHENTICATION_FAILED = "authentication_failed"
    INVALID_INPUT = "invalid_input"
    SOURCE_IMAGE_UNREACHABLE = "source_image_unreachable"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    RATE_LIMITED = "rate_limited"
    MODERATION_REJECTED = "moderation_rejected"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_FAILED = "provider_failed"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"


# Categories where retrying the same request cannot succeed without a change
# from the user (a different image, different credentials, waiting for a
# billing top-up) or a policy decision. These are reported as non-retryable
# so the worker does not burn attempts resubmitting a request that will fail
# the same way every time.
_NON_RETRYABLE_CATEGORIES = frozenset({
    SeedanceErrorCategory.AUTHENTICATION_FAILED,
    SeedanceErrorCategory.INVALID_INPUT,
    SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE,
    SeedanceErrorCategory.INSUFFICIENT_CREDITS,
    SeedanceErrorCategory.MODERATION_REJECTED,
    SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE,
})

_HTTP_STATUS_CATEGORY = {
    401: SeedanceErrorCategory.AUTHENTICATION_FAILED,
    403: SeedanceErrorCategory.AUTHENTICATION_FAILED,
    402: SeedanceErrorCategory.INSUFFICIENT_CREDITS,
    422: SeedanceErrorCategory.INVALID_INPUT,
    429: SeedanceErrorCategory.RATE_LIMITED,
}


class SeedanceProviderError(RuntimeError):
    """A sanitized Seedance/fal.ai failure.

    ``str(exc)`` is built only from a fixed prefix, the stable category, and
    an optional numeric HTTP status — never the provider response body,
    signed URLs, or credentials — so it stays safe when the worker writes it
    into ``media_jobs.last_error`` and the UI shows it to the user.
    """

    def __init__(self, category: str, *, status_code: int | None = None):
        self.category = category
        self.status_code = status_code
        self.retryable = category not in _NON_RETRYABLE_CATEGORIES
        suffix = f" (HTTP {int(status_code)})" if isinstance(status_code, int) else ""
        super().__init__(f"Seedance video generation failed: {category}{suffix}")


def _categorize_http_error(exc: "fal_client.FalClientHTTPError") -> SeedanceProviderError:
    status_code = getattr(exc, "status_code", None)
    error_type = str(getattr(exc, "error_type", "") or "").lower()

    if "moderat" in error_type or "content_polic" in error_type or "nsfw" in error_type:
        return SeedanceProviderError(SeedanceErrorCategory.MODERATION_REJECTED, status_code=status_code)
    if "image" in error_type and ("fetch" in error_type or "download" in error_type or "unreachable" in error_type):
        return SeedanceProviderError(SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE, status_code=status_code)

    category = _HTTP_STATUS_CATEGORY.get(status_code)
    if category:
        return SeedanceProviderError(category, status_code=status_code)
    if isinstance(status_code, int) and status_code >= 500:
        return SeedanceProviderError(SeedanceErrorCategory.PROVIDER_FAILED, status_code=status_code)
    return SeedanceProviderError(SeedanceErrorCategory.PROVIDER_FAILED, status_code=status_code)


def _categorize_error(exc: Exception) -> SeedanceProviderError:
    """Map any exception raised by fal_client into a sanitized category.

    Never inspects/forwards the exception's message text into the returned
    error beyond the fixed category vocabulary — provider response bodies and
    signed URLs must not leak into logs or ``media_jobs.last_error``.
    """
    if isinstance(exc, SeedanceProviderError):
        return exc
    if isinstance(exc, fal_client.FalClientHTTPError):
        return _categorize_http_error(exc)
    if isinstance(exc, fal_client.FalClientTimeoutError):
        return SeedanceProviderError(SeedanceErrorCategory.PROVIDER_TIMEOUT)
    return SeedanceProviderError(SeedanceErrorCategory.PROVIDER_FAILED)


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


def _duration_for(duration_seconds: float) -> str:
    """Return a Seedance-supported duration enum value (4..15 seconds)."""
    try:
        duration = int(round(float(duration_seconds)))
    except (TypeError, ValueError):
        duration = 5
    return str(max(4, min(15, duration)))


def _aspect_ratio_for(aspect_ratio: str) -> str:
    value = (aspect_ratio or "auto").strip()
    if value in _ALLOWED_ASPECT_RATIOS:
        return value
    return "auto"


def _estimate_cost(duration_seconds: float, model: str) -> float:
    rate = _COST_PER_SECOND.get(model, 0.3034)
    duration = int(_duration_for(duration_seconds))
    return round(rate * duration, 4)


def _public_image_url(image_url: str) -> str:
    """Return an HTTPS URL that fal.ai can fetch from the public internet.

    AI Film OS may persist internally served media as `/generated/...`. That is
    valid in the browser but not fetchable by fal.ai unless it is expanded to
    the service's public Render URL. Absolute URLs must already be public
    HTTPS endpoints; local/private hosts are rejected before a paid request is
    submitted.
    """
    value = str(image_url or "").strip()
    if not value:
        raise SeedanceProviderError(SeedanceErrorCategory.INVALID_INPUT)

    if value.startswith("/"):
        public_base = (
            os.getenv("PUBLIC_BASE_URL", "").strip()
            or os.getenv("RENDER_EXTERNAL_URL", "").strip()
        )
        if not public_base:
            raise SeedanceProviderError(SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE)
        base = urlparse(public_base)
        if base.scheme != "https" or not base.hostname:
            raise SeedanceProviderError(SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE)
        return f"{public_base.rstrip('/')}/{value.lstrip('/')}"

    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SeedanceProviderError(SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE)

    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".local"):
        raise SeedanceProviderError(SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        raise SeedanceProviderError(SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE)

    return value


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
    raise SeedanceProviderError(SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE)


def _encode_task_id(model: str, request_id: str) -> str:
    return f"{model}{_TASK_ID_SEPARATOR}{request_id}"


def _decode_task_id(task_id: str) -> tuple[str, str]:
    model, sep, request_id = str(task_id or "").partition(_TASK_ID_SEPARATOR)
    if not sep or not model or not request_id:
        raise SeedanceProviderError(SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE)
    return model, request_id


class SeedanceProvider:
    """Seedance 2.0 via fal.ai's official Python client.

    Non-blocking submit()/check_task() pair — see module docstring for why
    the blocking ``fal_client.subscribe``/``handler.get()`` calls are never
    used here.
    """

    name = "seedance"

    def __init__(self):
        key = settings.fal_api_key.strip()
        if not key:
            raise VideoProviderNotConfigured("FAL_API_KEY not set.")

        # fal-client reads FAL_KEY. Copy the already server-side Render secret
        # into the SDK's expected environment variable without logging it.
        os.environ["FAL_KEY"] = key

    def submit(self, request: VideoGenerationRequest) -> str:
        """Submit a video generation request to fal.ai's queue. Non-blocking.

        Returns an opaque task id encoding the model and fal.ai request id.
        The caller must persist this id (``jobs.record_provider_task_id``)
        before calling ``check_task`` so a crash between submit and the first
        poll still resumes this exact request on restart.
        """
        model = _model_for(request.model_profile)

        # Seedance 2.0 accepts resolution/aspect_ratio enums rather than raw
        # width/height. AI Film OS keeps audio generation separate, so native
        # Seedance audio is explicitly disabled here.
        payload = {
            "image_url": _public_image_url(request.image_url),
            "prompt": _build_prompt(request),
            "duration": _duration_for(request.duration_seconds),
            "resolution": "720p",
            "aspect_ratio": _aspect_ratio_for(request.aspect_ratio),
            "generate_audio": False,
        }

        try:
            handler = fal_client.submit(model, arguments=payload)
        except (VideoProviderNotConfigured, SeedanceProviderError):
            raise
        except Exception as exc:
            raise _categorize_error(exc) from exc

        request_id = str(getattr(handler, "request_id", "") or "")
        if not request_id:
            raise SeedanceProviderError(SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE)
        return _encode_task_id(model, request_id)

    def check_task(self, task_id: str) -> dict:
        """Single non-blocking status check for a previously submitted task.

        Returns:
            {"status": "pending"|"succeed"|"failed", "url": str, "reason": str}
        ``reason`` is always a stable ``SeedanceErrorCategory`` value, never
        provider-authored text.
        """
        model, request_id = _decode_task_id(task_id)

        try:
            status = fal_client.status(model, request_id, with_logs=False)
        except (VideoProviderNotConfigured, SeedanceProviderError):
            raise
        except Exception as exc:
            error = _categorize_error(exc)
            return {"status": "failed", "url": "", "reason": error.category}

        if not isinstance(status, fal_client.Completed):
            return {"status": "pending", "url": "", "reason": ""}

        if status.error:
            error_type = str(status.error_type or "").lower()
            if "moderat" in error_type or "content_polic" in error_type or "nsfw" in error_type:
                category = SeedanceErrorCategory.MODERATION_REJECTED
            elif "image" in error_type:
                category = SeedanceErrorCategory.SOURCE_IMAGE_UNREACHABLE
            else:
                category = SeedanceErrorCategory.PROVIDER_FAILED
            return {"status": "failed", "url": "", "reason": category}

        try:
            result_body = fal_client.result(model, request_id)
        except Exception as exc:
            error = _categorize_error(exc)
            return {"status": "failed", "url": "", "reason": error.category}

        if not isinstance(result_body, dict):
            return {
                "status": "failed",
                "url": "",
                "reason": SeedanceErrorCategory.INVALID_PROVIDER_RESPONSE,
            }

        try:
            video_url = _extract_video_url(result_body)
        except SeedanceProviderError as exc:
            return {"status": "failed", "url": "", "reason": exc.category}

        return {"status": "succeed", "url": video_url, "reason": ""}

    def cost_for(self, request: VideoGenerationRequest) -> float:
        model = _model_for(request.model_profile)
        return _estimate_cost(request.duration_seconds, model)

    def model_for(self, request: VideoGenerationRequest) -> str:
        return _model_for(request.model_profile)
